"""arq worker entrypoint: `arq app.worker.WorkerSettings`.

Runs as its own compose service on the backend image. Jobs carry explicit
org context (enforced again inside each job — D7).
"""

from arq.connections import RedisSettings

from app.agents.runner import execute_run
from app.config import get_settings
from app.ingestion.pipeline import ingest_document


class WorkerSettings:
    functions = [ingest_document, execute_run]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Concurrency limit (spec 03 §6): triage runs hold an LLM connection, so
    # unbounded parallelism would swamp a local Ollama.
    max_jobs = get_settings().worker_concurrency
    # Job timeout sits above the per-run timeout so the run's own handler wins
    # and records a typed `timeout` failure rather than arq killing it silently.
    job_timeout = get_settings().run_timeout_seconds + 60
