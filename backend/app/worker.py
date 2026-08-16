"""arq worker entrypoint: `arq app.worker.WorkerSettings`.

Runs as its own compose service on the backend image. Jobs carry explicit
org context (enforced again inside each job — D7).
"""

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.agents.checkpointer import ensure_schema
from app.agents.runner import (
    execute_run,
    reconcile_runs,
    recover_stranded_runs,
    resume_run,
)
from app.config import get_settings
from app.ingestion.pipeline import ingest_document


async def startup(ctx: dict[str, Any]) -> None:
    """Prepare the checkpoint schema, then recover runs a previous worker died in.

    Schema first, and before any job can start: langgraph's setup ends in
    CREATE INDEX CONCURRENTLY, which waits for every older transaction. Run
    from inside a job — which holds one open for the whole run — it deadlocks
    against the very run that triggered it.
    """
    try:
        await ensure_schema()
    except Exception:  # noqa: BLE001 - a cold stack has no tables yet either
        logging.getLogger(__name__).warning("checkpoint schema setup deferred", exc_info=True)

    recovered = await recover_stranded_runs()
    if recovered:
        logging.getLogger(__name__).warning("re-enqueued %d stranded run(s)", recovered)


class WorkerSettings:
    functions = [ingest_document, execute_run, resume_run]
    # Reconcile every 5s. A decision commits before its resume is enqueued, so
    # a queue outage in that window leaves an irreversible decision with
    # nothing to act on it — and the approver cannot retry, because a second
    # decision is correctly refused with 409. `unique=True` keeps one worker
    # doing it when several are running.
    cron_jobs = [
        cron(reconcile_runs, second=set(range(0, 60, 5)), unique=True, run_at_startup=True)
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Concurrency limit (spec 03 §6): triage runs hold an LLM connection, so
    # unbounded parallelism would swamp a local Ollama.
    on_startup = startup
    max_jobs = get_settings().worker_concurrency
    # Job timeout sits above the per-run timeout so the run's own handler wins
    # and records a typed `timeout` failure rather than arq killing it silently.
    job_timeout = get_settings().run_timeout_seconds + 60
    # Graceful shutdown (spec 05 §4): on SIGTERM, let an in-flight run finish
    # instead of aborting it mid-write. The grace exceeds job_timeout so the
    # longest legal job can complete; anything still running past that was
    # already going to be killed by its own timeout.
    #
    # A job that does get cut off is not lost — it is left in `executing` or
    # `queued` and the reconciler re-enqueues it, which is why replay had to be
    # idempotent (G3.3) before this was safe to rely on.
    handle_signals = True
    job_completion_wait = get_settings().run_timeout_seconds + 90
    # Retries are bounded here as well as in the run row. arq's own counter
    # governs redelivery; `runs.attempts` is what survives Redis losing the
    # job entirely, and dead-letters the run when it does not.
    max_tries = get_settings().max_run_attempts
