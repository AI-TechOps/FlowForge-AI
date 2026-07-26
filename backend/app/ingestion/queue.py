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


async def enqueue_ingest(document_id: uuid.UUID, org_id: uuid.UUID) -> None:
    queue = await get_queue()
    await queue.enqueue_job("ingest_document", str(document_id), str(org_id))
