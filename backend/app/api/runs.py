import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_VERSION
from app.auth.principal import ANY_PERSONA, OPERATOR_WORK, Principal
from app.db import get_session
from app.ingestion.queue import enqueue_run
from app.models import AuditLog, FailureReason, Run, RunStatus, Ticket

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_summary(run: Run) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "ticket_id": str(run.ticket_id),
        "status": run.status.value,
        "agent_version": run.agent_version,
        "confidence": run.confidence,
        "failure_reason": run.failure_reason.value if run.failure_reason else None,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


class RunCreate(BaseModel):
    ticket_id: uuid.UUID


@router.post("/api/runs", status_code=202)
async def create_run(
    payload: RunCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = OPERATOR_WORK,
) -> dict[str, Any]:
    """Start a triage run. The canonical way to trigger the agent.

    A run is a resource in its own right — it has a lifecycle, a detail page,
    and an approval hanging off it — so it is created by POSTing to the
    collection that lists it. `/api/tickets/{id}/triage` predates this and
    remains as an alias.
    """
    return await _start_run(session, principal.org_id, payload.ticket_id)


@router.post("/api/tickets/{ticket_id}/triage", status_code=202)
async def start_triage(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = OPERATOR_WORK,
) -> dict[str, Any]:
    """Alias for `POST /api/runs`, kept so Phase 1-3 callers keep working."""
    return await _start_run(session, principal.org_id, ticket_id)


async def _start_run(
    session: AsyncSession, org_id: uuid.UUID, ticket_id: uuid.UUID
) -> dict[str, Any]:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.org_id != org_id:
        raise HTTPException(status_code=404, detail="ticket not found")

    run = Run(
        org_id=org_id,
        ticket_id=ticket.id,
        status=RunStatus.queued,
        agent_version=AGENT_VERSION,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # The durable row is committed before the job is enqueued, so a Redis
    # outage here used to strand the run in `queued` forever: no worker would
    # ever claim it and nothing reconciled it (Codex Phase 2 finding 7). A run
    # that cannot be started is a failed run, and says so.
    try:
        await enqueue_run(run.id, org_id)
    except Exception as exc:
        run.status = RunStatus.failed
        run.failure_reason = FailureReason.internal_error
        run.error = f"could not enqueue the triage job: {exc}"[:2000]
        run.finished_at = datetime.now(UTC)
        await session.commit()
        logger.exception("failed to enqueue run %s", run.id)
        raise HTTPException(
            status_code=503, detail="triage queue unavailable; run marked failed"
        ) from exc

    return {"id": str(run.id), "status": run.status.value}


@router.get("/api/runs")
async def list_runs(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ANY_PERSONA,
    status: RunStatus | None = Query(default=None),
    ticket_id: uuid.UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    statement = select(Run).where(Run.org_id == principal.org_id)
    if status is not None:
        statement = statement.where(Run.status == status)
    if ticket_id is not None:
        statement = statement.where(Run.ticket_id == ticket_id)
    runs = (await session.execute(statement.order_by(Run.created_at.desc()))).scalars().all()
    return [_run_summary(run) for run in runs]


@router.get("/api/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ANY_PERSONA,
) -> dict[str, Any]:
    """Full run detail: status, structured output, evidence, and audit trail."""
    org_id = principal.org_id
    run = await session.get(Run, run_id)
    if run is None or run.org_id != org_id:
        raise HTTPException(status_code=404, detail="run not found")

    entries = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.run_id == run.id, AuditLog.org_id == org_id)
                .order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_run_summary(run),
        "output": run.output,
        "evidence": run.evidence or [],
        "audit_entries": [
            {
                "actor": entry.actor,
                "tool": entry.tool,
                "payload": entry.payload,
                "result": entry.result,
                "latency_ms": entry.latency_ms,
                "tokens_in": entry.tokens_in,
                "tokens_out": entry.tokens_out,
                "cost_estimate": entry.cost_estimate,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in entries
        ],
    }
