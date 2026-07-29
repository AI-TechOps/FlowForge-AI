import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_VERSION
from app.api.deps import current_org_id
from app.db import get_session
from app.ingestion.queue import enqueue_run
from app.models import AuditLog, Run, RunStatus, Ticket

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


@router.post("/api/tickets/{ticket_id}/triage", status_code=202)
async def start_triage(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
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

    await enqueue_run(run.id, org_id)
    return {"id": str(run.id), "status": run.status.value}


@router.get("/api/runs")
async def list_runs(
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
    status: RunStatus | None = Query(default=None),
    ticket_id: uuid.UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    statement = select(Run).where(Run.org_id == org_id)
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
    org_id: uuid.UUID = Depends(current_org_id),
) -> dict[str, Any]:
    """Full run detail: status, structured output, evidence, and audit trail."""
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
        "audit": [
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
