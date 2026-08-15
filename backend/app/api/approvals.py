import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import audit
from app.agents.write_tools import WRITE_TOOLS
from app.api.deps import current_org_id, current_user_id
from app.db import get_session
from app.ingestion.queue import enqueue_resume
from app.models import Approval, ApprovalStatus, Decision, Run, Ticket

router = APIRouter()


class ProposedActionIn(BaseModel):
    # extra="allow" so an approver can send the card's action back with only
    # `args` changed and keep its display context (field, current_value). That
    # context is what makes the stored decision readable later: "priority
    # P4 → P3" rather than a bare argument dict.
    model_config = ConfigDict(extra="allow")

    tool: str
    args: dict[str, Any]


class DecisionIn(BaseModel):
    decision: Decision
    # Only meaningful for `edited`; validated against each tool's own schema
    # before it is stored, so an invalid edit is rejected at the API rather
    # than blowing up mid-execute after the run has already resumed.
    final_values: list[ProposedActionIn] | None = None
    feedback: str | None = Field(default=None, max_length=5000)


def _approval_summary(approval: Approval) -> dict[str, Any]:
    return {
        "id": str(approval.id),
        "run_id": str(approval.run_id),
        "status": approval.status.value,
        "risk_class": approval.risk_class.value,
        "decision": approval.decision.value if approval.decision else None,
        "approver_user_id": str(approval.approver_user_id) if approval.approver_user_id else None,
        "created_at": approval.created_at.isoformat(),
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


@router.get("/api/approvals")
async def list_approvals(
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
    status: ApprovalStatus | None = Query(default=None),
) -> list[dict[str, Any]]:
    statement = select(Approval).where(Approval.org_id == org_id)
    if status is not None:
        statement = statement.where(Approval.status == status)
    approvals = (
        (await session.execute(statement.order_by(Approval.created_at.desc()))).scalars().all()
    )
    return [_approval_summary(a) for a in approvals]


@router.get("/api/approvals/{approval_id}")
async def get_approval(
    approval_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
) -> dict[str, Any]:
    """The approval card: everything a human needs to decide, in one payload.

    Deliberately includes the evidence and the agent's confidence. An approver
    asked to authorise a write on an agent's say-so needs to see what the agent
    read, not just what it concluded.
    """
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.org_id != org_id:
        raise HTTPException(status_code=404, detail="approval not found")

    run = await session.get(Run, approval.run_id)
    ticket = await session.get(Ticket, run.ticket_id) if run else None
    output = (run.output if run else None) or {}

    actions = approval.original_proposal or []
    return {
        **_approval_summary(approval),
        "proposed_actions": actions,
        # Same list under the column's own name, so the audit contract and the
        # card speak the same language (spec 04 §5).
        "original_proposal": actions,
        # New vs existing, side by side. The MVP approval card requires both:
        # "change priority to P1" is not reviewable without knowing it is
        # currently P4.
        "new_values": {a.get("field"): a.get("new_value") for a in actions},
        "existing_values": {a.get("field"): a.get("current_value") for a in actions},
        "final_values": approval.final_values,
        "feedback": approval.feedback,
        "agent_version": run.agent_version if run else None,
        "confidence": run.confidence if run else None,
        "summary": output.get("summary"),
        "recommended_resolution": output.get("recommended_resolution"),
        "citations": output.get("citations", []),
        "evidence": (run.evidence if run else None) or [],
        "ticket": (
            {
                "id": str(ticket.id),
                "title": ticket.title,
                "status": ticket.status.value,
                "priority": ticket.priority,
                "assigned_team": ticket.assigned_team,
            }
            if ticket
            else None
        ),
    }


@router.post("/api/approvals/{approval_id}/decision")
async def decide(
    approval_id: uuid.UUID,
    payload: DecisionIn,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
    user_id: uuid.UUID = Depends(current_user_id),
) -> dict[str, Any]:
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.org_id != org_id:
        raise HTTPException(status_code=404, detail="approval not found")

    final_values = None
    if payload.decision == Decision.edited:
        if not payload.final_values:
            raise HTTPException(status_code=422, detail="edited decisions require final_values")
        run = await session.get(Run, approval.run_id)
        final_values = _validate_edits(
            payload.final_values,
            allowed_ticket_id=run.ticket_id if run else None,
            allowed_tools={a.get("tool") for a in (approval.original_proposal or [])},
        )

    # The one-shot rule (G3.7) as a single compare-and-swap: the UPDATE only
    # matches while the row is still pending, so two concurrent requests cannot
    # both win — the loser changes zero rows and gets a 409. A read-then-write
    # would leave a window where both see `pending`.
    result = await session.execute(
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == ApprovalStatus.pending)
        .values(
            status=ApprovalStatus.decided,
            decision=payload.decision,
            approver_user_id=user_id,
            final_values=final_values,
            feedback=payload.feedback,
            decided_at=datetime.now(UTC),
        )
    )
    if result.rowcount == 0:
        await session.rollback()
        raise HTTPException(status_code=409, detail="approval has already been decided")
    await session.commit()

    # The human decision is itself an auditable event, and it is the one entry
    # that carries BOTH what the agent proposed and what the human authorised
    # (G3.4). Without it the trail shows the writes but not who sanctioned them
    # or what they changed on the way through.
    await audit.record(
        org_id=org_id,
        run_id=approval.run_id,
        actor=f"user:{user_id}",
        tool="approval.decision",
        payload={
            "decision": payload.decision.value,
            "original_proposal": approval.original_proposal,
            "final_values": final_values,
            "feedback": payload.feedback,
        },
        result={"approval_id": str(approval_id)},
    )

    # Enqueued only after the decision is durably committed: a resume that ran
    # before the commit could read a still-pending approval and do nothing.
    await enqueue_resume(approval.run_id, org_id)
    await session.refresh(approval)
    return _approval_summary(approval)


def _validate_edits(
    actions: list[ProposedActionIn],
    *,
    allowed_ticket_id: uuid.UUID | None,
    allowed_tools: set[str | None],
) -> list[dict[str, Any]]:
    """Validate each edited action, and bind it to what was actually proposed.

    Schema validity is not enough. "Edit" means *adjust the values on this
    card*, not *submit an arbitrary write request*: an approver looking at
    ticket A must not be able to authorise a write against ticket B, nor invoke
    a tool that was never proposed and never risk-classified. Without these
    bounds the approval card stops describing what the decision authorises,
    and the human-in-the-loop is reviewing one thing while approving another.

    Rejecting here also means an invalid edit never reaches the resumed graph,
    so a bad edit is a 422 on the approver's request rather than a run that
    fails halfway through the write path (G3.4).
    """
    validated: list[dict[str, Any]] = []
    for action in actions:
        tool = WRITE_TOOLS.get(action.tool)
        if tool is None:
            raise HTTPException(
                status_code=422, detail=f"{action.tool} is not an approvable write tool"
            )
        if action.tool not in allowed_tools:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{action.tool} was not part of the proposal under review; "
                    "an edit may adjust proposed actions, not add new ones"
                ),
            )
        edited_ticket = action.args.get("ticket_id")
        if allowed_ticket_id is not None and str(edited_ticket) != str(allowed_ticket_id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "edited actions must target the ticket shown on the approval "
                    f"card ({allowed_ticket_id}), not {edited_ticket}"
                ),
            )
        try:
            args = tool.args_model.model_validate(action.args)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid arguments for {action.tool}: {exc}"
            ) from exc
        # Preserve everything the approver sent, but substitute the *validated*
        # arguments so the stored decision is exactly what will execute.
        stored = action.model_dump(mode="json")
        stored["args"] = args.model_dump(mode="json")
        validated.append(stored)
    return validated
