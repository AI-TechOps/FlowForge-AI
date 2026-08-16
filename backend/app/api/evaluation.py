"""Evaluation endpoints (spec 06 §2). Administrator only.

Starting a batch triages every seed ticket, which costs real model time and
writes a row that later phases compare against — oversight work, and the
personas doc gives oversight to the Administrator.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_VERSION
from app.auth.principal import ADMIN_ONLY, Principal
from app.db import get_session
from app.eval.batch import batch_payload, load_labels, new_batch, result_payload
from app.ingestion.queue import enqueue_eval_batch, enqueue_run
from app.models import EvalBatch, EvalResult, Run, RunStatus, Ticket
from app.tenancy import get_scoped

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/eval/run", status_code=202)
async def start_eval_batch(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> dict[str, Any]:
    """Triage every seed ticket as one batch, then score it.

    202, not 200: the batch is accepted and runs in the background (D19
    decision 4). Twenty sequential model calls is minutes of work, and holding
    an HTTP connection open for it would make one slow run everybody's problem.
    """
    org_id = principal.org_id
    labels = load_labels()

    tickets = (
        (
            await session.execute(
                select(Ticket).where(Ticket.org_id == org_id, Ticket.is_eval_seed.is_(True))
            )
        )
        .scalars()
        .all()
    )
    scoreable = [t for t in tickets if (t.external_ref or "") in labels]
    if not scoreable:
        raise HTTPException(
            status_code=409,
            detail=(
                "no labelled seed tickets in this organization; run scripts/load_eval_tickets.py"
            ),
        )

    batch = new_batch(org_id, len(scoreable))
    session.add(batch)
    await session.flush()

    for ticket in scoreable:
        run = Run(
            org_id=org_id,
            ticket_id=ticket.id,
            status=RunStatus.queued,
            agent_version=AGENT_VERSION,
            triggered_by=principal.user_id,
            # The marker that selects the eval graph. Set here and nowhere
            # else — this endpoint is the only thing in the system that creates
            # a run which cannot pause for approval.
            eval_batch_id=batch.id,
        )
        session.add(run)
        await session.flush()
        await enqueue_run(run.id, org_id, principal.user_id)

    await session.commit()
    # Enqueued after the runs so the scorer never starts before its subjects
    # exist; it polls for settlement anyway, but starting it on an empty set
    # would burn its whole deadline waiting for rows that were still committing.
    await enqueue_eval_batch(batch.id, org_id)
    await session.refresh(batch)
    logger.info(
        "eval batch %s started over %s seed tickets",
        batch.id,
        len(scoreable),
        extra={"eval_batch_id": str(batch.id)},
    )
    return batch_payload(batch)


@router.get("/api/eval/batches")
async def list_batches(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Newest first — the regression table, most recent run at the top (G5.5)."""
    batches = (
        (
            await session.execute(
                select(EvalBatch)
                .where(EvalBatch.org_id == principal.org_id)
                .order_by(EvalBatch.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [batch_payload(b) for b in batches]


@router.get("/api/eval/batches/{batch_id}")
async def get_batch(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> dict[str, Any]:
    """The batch summary plus every per-ticket result.

    Results are included rather than paginated behind another call: twenty rows
    is the whole point of the Evaluation screen, and an accuracy figure you
    cannot drill into is a number nobody can act on.
    """
    batch = await get_scoped(session, EvalBatch, batch_id, principal.org_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="eval batch not found")

    results = (
        (
            await session.execute(
                select(EvalResult)
                .where(EvalResult.batch_id == batch.id)
                .order_by(EvalResult.seed_ref)
            )
        )
        .scalars()
        .all()
    )
    return {**batch_payload(batch), "results": [result_payload(r) for r in results]}
