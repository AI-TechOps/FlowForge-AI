import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.write_tools import WRITE_TOOLS
from app.api.deps import current_org_id, current_user_id
from app.db import get_session
from app.ingestion.queue import enqueue_resume
from app.models import Approval, ApprovalStatus, Decision, Run, Ticket

router = APIRouter()


class ProposedActionIn(BaseModel):
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

    return {
        **_approval_summary(approval),
        "proposed_actions": approval.original_proposal,
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
        final_values = _validate_edits(payload.final_values)

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

    # Enqueued only after the decision is durably committed: a resume that ran
    # before the commit could read a still-pending approval and do nothing.
    await enqueue_resume(approval.run_id, org_id)
    await session.refresh(approval)
    return _approval_summary(approval)


def _validate_edits(actions: list[ProposedActionIn]) -> list[dict[str, Any]]:
    """Validate each edited action against its own tool's Pydantic schema.

    Rejecting here means an invalid edit never reaches the resumed graph, so a
    bad edit is a 422 on the approver's request rather than a run that fails
    halfway through the write path (G3.4).
    """
    validated: list[dict[str, Any]] = []
    for action in actions:
        tool = WRITE_TOOLS.get(action.tool)
        if tool is None:
            raise HTTPException(
                status_code=422, detail=f"{action.tool} is not an approvable write tool"
            )
        try:
            args = tool.args_model.model_validate(action.args)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid arguments for {action.tool}: {exc}"
            ) from exc
        validated.append({"tool": action.tool, "args": args.model_dump(mode="json")})
    return validated
