"""Job enqueueing. Every payload carries the full authority context.

Spec 05 §4 requires background job payloads to carry `org_id` *and* the acting
user id. Only the org was travelling, which left two gaps: a worker could not
verify the complete authority context the caller claimed to have, and the audit
trail could not answer which human set the work in motion (Codex Phase 4
finding 7).

`actor_user_id` is optional in the signatures, and deliberately so — recovery
re-enqueues a run long after the original request is gone, and the reconciler
is not a human. A job with no actor is system-initiated, which is a true
statement rather than a missing field. For the initial triage job the actor is
also persisted on the run, so recovery can restore what the queue no longer
remembers.
"""

import uuid
from datetime import timedelta

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


def _actor(actor_user_id: uuid.UUID | None) -> str | None:
    return str(actor_user_id) if actor_user_id else None


def run_job_id(prefix: str, run_id: uuid.UUID, started_at: object | None) -> str:
    """A job id that is stable until the job actually runs.

    Without this the reconciler is a retry amplifier. It fires every 5 seconds
    and re-enqueues anything past the cutoff, but re-enqueueing does not change
    a run's status — so a run that stays queued stays eligible, and each tick
    adds another job. One stalled run became hundreds of duplicates, the
    backlog pushed more runs past the cutoff, and six Phase 2 gates timed out
    waiting behind a queue full of copies of each other.

    arq drops an enqueue whose job id is already pending, so keying on
    `started_at` collapses every repeat tick into the one job that is still
    waiting. Both claim paths set `started_at` when they actually take the run,
    which changes the key — so a genuine later recovery is not suppressed by
    the earlier attempt's stored result.
    """
    stamp = int(started_at.timestamp()) if started_at is not None else 0
    return f"{prefix}:{run_id}:{stamp}"


async def enqueue_ingest(
    document_id: uuid.UUID,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    queue = await get_queue()
    await queue.enqueue_job("ingest_document", str(document_id), str(org_id), _actor(actor_user_id))


async def enqueue_run(
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    started_at: object | None = None,
) -> None:
    """Jobs carry explicit org and actor context; the worker enforces org again (D7)."""
    queue = await get_queue()
    await queue.enqueue_job(
        "execute_run",
        str(run_id),
        str(org_id),
        _actor(actor_user_id),
        _job_id=run_job_id("execute", run_id, started_at),
    )


async def enqueue_eval_batch(
    batch_id: uuid.UUID,
    org_id: uuid.UUID,
    attempt: int = 0,
    defer_seconds: int = 0,
) -> None:
    """Score an eval batch once its runs settle (spec 06 §2).

    Keyed by batch id *and attempt*: a duplicate delivery of one attempt
    collapses into a single scorer, while the scorer re-checking later is a new
    job rather than a duplicate arq refuses to enqueue. The scorer re-enqueues
    itself instead of sleeping, so no job outlives `job_timeout` waiting for a
    twenty-run batch to finish.
    """
    queue = await get_queue()
    await queue.enqueue_job(
        "score_batch",
        str(batch_id),
        str(org_id),
        attempt,
        _job_id=f"eval:{batch_id}:{attempt}",
        _defer_by=timedelta(seconds=defer_seconds) if defer_seconds else None,
    )


async def enqueue_resume(
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    started_at: object | None = None,
) -> None:
    """Continue a paused run after a human decision (Phase 3).

    The deciding human is the authority for everything the resume goes on to
    write, so their id rides with the job rather than being re-derived.
    """
    queue = await get_queue()
    await queue.enqueue_job(
        "resume_run",
        str(run_id),
        str(org_id),
        _actor(actor_user_id),
        _job_id=run_job_id("resume", run_id, started_at),
    )
