"""arq worker entrypoint: `arq app.worker.WorkerSettings`.

Runs as its own compose service on the backend image. Jobs carry explicit
org context (enforced again inside each job — D7).
"""

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.agents.runner import (
    execute_run,
    reconcile_runs,
    recover_stranded_runs,
    resume_run,
)
from app.config import get_settings
from app.ingestion.pipeline import ingest_document


async def startup(ctx: dict[str, Any]) -> None:
    """Recover runs a previous worker died in the middle of."""
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
