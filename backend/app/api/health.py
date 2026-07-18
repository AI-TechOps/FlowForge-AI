import redis.asyncio as aioredis
from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

router = APIRouter()


async def _check_db() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


async def _check_redis() -> str:
    # Client construction stays inside the guard: a malformed REDIS_URL must
    # surface as {"redis": "error"}, never as an HTTP 500.
    client = None
    try:
        client = aioredis.from_url(get_settings().redis_url)
        await client.ping()
        return "ok"
    except Exception:
        return "error"
    finally:
        if client is not None:
            await client.aclose()


@router.get("/api/health")
async def health() -> dict[str, str]:
    db_status = await _check_db()
    redis_status = await _check_redis()
    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return {"status": overall, "db": db_status, "redis": redis_status}
