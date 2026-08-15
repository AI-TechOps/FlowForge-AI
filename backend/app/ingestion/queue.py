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
) -> None:
    """Jobs carry explicit org and actor context; the worker enforces org again (D7)."""
    queue = await get_queue()
    await queue.enqueue_job("execute_run", str(run_id), str(org_id), _actor(actor_user_id))


async def enqueue_resume(
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Continue a paused run after a human decision (Phase 3).

    The deciding human is the authority for everything the resume goes on to
    write, so their id rides with the job rather than being re-derived.
    """
    queue = await get_queue()
    await queue.enqueue_job("resume_run", str(run_id), str(org_id), _actor(actor_user_id))
