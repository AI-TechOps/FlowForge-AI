"""LangGraph Postgres checkpointer.

Wired in Phase 2 even though nothing pauses yet: Phase 3's durable interrupt
depends on this plumbing already being correct and migrated, and discovering
checkpoint problems while also building the approval flow would conflate two
hard things.

Driver note (D16 decision 5): langgraph-checkpoint-postgres speaks psycopg3
while the application runs on asyncpg. Two drivers against one database is a
deliberate, documented trade — not drift.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings


def psycopg_dsn(database_url: str | None = None) -> str:
    """Convert the app's SQLAlchemy URL into a plain psycopg DSN."""
    url = database_url or get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@asynccontextmanager
async def checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Open a checkpointer for the lifetime of a run.

    `setup()` creates LangGraph's own checkpoint tables if absent. They live
    outside Alembic on purpose: they are the library's schema, versioned with
    the library, and hand-managing them in our migrations would fight upgrades.
    """
    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn()) as saver:
        await saver.setup()
        yield saver
