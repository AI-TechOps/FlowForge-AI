"""arq worker entrypoint: `arq app.worker.WorkerSettings`.

Runs as its own compose service on the backend image. Jobs carry explicit
org context (enforced again inside each job — D7).
"""

from arq.connections import RedisSettings

from app.config import get_settings
from app.ingestion.pipeline import ingest_document


class WorkerSettings:
    functions = [ingest_document]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 300
