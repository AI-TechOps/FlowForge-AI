import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_VERSION
from app.auth.principal import ANY_PERSONA, OPERATOR_WORK, Principal
from app.db import get_session
from app.ingestion.queue import enqueue_run
from app.logging_config import bind_run
from app.models import AuditLog, FailureReason, Run, RunStatus, Ticket
from app.tenancy import get_scoped

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
        # Present so a consumer can tell an eval run from a real one. The run
        # history is a record of what the agent did for people; twenty eval
        # runs appearing there unlabelled would read as twenty tickets nobody
        # remembers filing.
        "eval_batch_id": str(run.eval_batch_id) if run.eval_batch_id else None,
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
    return await _start_run(session, principal, payload.ticket_id)


@router.post("/api/tickets/{ticket_id}/triage", status_code=202)
async def start_triage(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = OPERATOR_WORK,
) -> dict[str, Any]:
    """Alias for `POST /api/runs`, kept so Phase 1-3 callers keep working."""
    return await _start_run(session, principal, ticket_id)


async def _start_run(
    session: AsyncSession, principal: Principal, ticket_id: uuid.UUID
) -> dict[str, Any]:
    org_id = principal.org_id
    ticket = await get_scoped(session, Ticket, ticket_id, org_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    run = Run(
        org_id=org_id,
        ticket_id=ticket.id,
        status=RunStatus.queued,
        agent_version=AGENT_VERSION,
        # Who asked for this run. Persisted as well as enqueued: a recovery
        # re-enqueue happens long after the request is gone, and without the
        # column the original human is unrecoverable.
        triggered_by=principal.user_id,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    # From here the API's lines carry the same run_id the worker will stamp on
    # its own, so "what happened to run X?" is one query across two containers
    # rather than a timestamp-matching exercise between them (spec 06 §3).
    bind_run(str(run.id))

    # The durable row is committed before the job is enqueued, so a Redis
    # outage here used to strand the run in `queued` forever: no worker would
    # ever claim it and nothing reconciled it (Codex Phase 2 finding 7). A run
    # that cannot be started is a failed run, and says so.
    try:
        await enqueue_run(run.id, org_id, principal.user_id)
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
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    include_eval: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Run history, filtered by status, date and ticket (spec 06 §3).

    Eval runs are excluded unless asked for. A batch adds twenty runs at once
    and they are not work anybody requested; leaving them in by default would
    make the history unreadable on the day the eval is used most.

    Paginated, and the response is an object rather than a bare list: `total`
    is what lets a dashboard say "20 of 143" instead of silently showing the
    first page as though it were everything.
    """
    filters = [Run.org_id == principal.org_id]
    if status is not None:
        filters.append(Run.status == status)
    if ticket_id is not None:
        filters.append(Run.ticket_id == ticket_id)
    if since is not None:
        filters.append(Run.created_at >= since)
    if until is not None:
        filters.append(Run.created_at <= until)
    if not include_eval:
        filters.append(Run.eval_batch_id.is_(None))

    total = (await session.execute(select(func.count(Run.id)).where(*filters))).scalar_one()
    runs = (
        (
            await session.execute(
                select(Run)
                .where(*filters)
                .order_by(Run.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [_run_summary(run) for run in runs],
    }


@router.get("/api/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ANY_PERSONA,
) -> dict[str, Any]:
    """Full run detail: status, structured output, evidence, and audit trail."""
    bind_run(str(run_id))
    org_id = principal.org_id
    run = await get_scoped(session, Run, run_id, org_id)
    if run is None:
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
