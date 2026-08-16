"""LangGraph Postgres checkpointer.

Wired in Phase 2 even though nothing pauses yet: Phase 3's durable interrupt
depends on this plumbing already being correct and migrated, and discovering
checkpoint problems while also building the approval flow would conflate two
hard things.

Driver note (D16 decision 5): langgraph-checkpoint-postgres speaks psycopg3
while the application runs on asyncpg. Two drivers against one database is a
deliberate, documented trade — not drift.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings

logger = logging.getLogger(__name__)

# Arbitrary but stable: two processes taking this lock agree they are both
# about to run the checkpointer's schema migration.
SETUP_ADVISORY_LOCK = 0x_F10_F0_6E

# Once per process. `setup()` is idempotent in intent but not concurrency-safe
# in practice, and it was being called on every single run.
_setup_lock = asyncio.Lock()
_setup_done = False


def psycopg_dsn(database_url: str | None = None) -> str:
    """Convert the app's SQLAlchemy URL into a plain psycopg DSN."""
    url = database_url or get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


async def ensure_schema() -> None:
    """Create the checkpointer's schema, once per process, on its own connection.

    Called at worker startup — deliberately *before* any job holds a database
    transaction, because that ordering is load-bearing.

    langgraph's `setup()` ends in `CREATE INDEX CONCURRENTLY`, and Postgres
    makes that statement wait for every transaction older than itself to
    finish. `execute_run` opens a transaction, keeps it open for the life of
    the run, and used to call `setup()` from inside it — so the index waited
    for the run, the run waited for the index, and the pair sat there until
    arq killed the job at 360s. Four such jobs saturated the worker and every
    later run queued behind them; six Phase 2 gates timed out with nothing
    wrong in Phase 2.

    Nothing in the deadlock is specific to a cold stack except that `setup()`
    only does real work once, which is exactly why it survived every warm run
    and only ever bit CI.

    Calling `setup()` per run was also a plain race: concurrent runs insert the
    same `checkpoint_migrations` row and one loses with

        duplicate key value violates unique constraint
        "checkpoint_migrations_pkey"  DETAIL: Key (v)=(6) already exists.

    reported as `internal_error` on a run that had nothing wrong with it.

    Two guards, because there are two kinds of race. The process-local flag and
    lock stop concurrent callers in *this* process; the Postgres advisory lock
    serializes the backend and worker containers, which share no memory. The
    advisory lock is session-scoped and released in a `finally`, so a failed
    setup does not wedge every other process.
    """
    global _setup_done
    if _setup_done:
        return
    async with _setup_lock:
        if _setup_done:
            return
        async with AsyncPostgresSaver.from_conn_string(psycopg_dsn()) as saver:
            await saver.conn.execute("SELECT pg_advisory_lock(%s)", (SETUP_ADVISORY_LOCK,))
            try:
                await saver.setup()
            finally:
                await saver.conn.execute("SELECT pg_advisory_unlock(%s)", (SETUP_ADVISORY_LOCK,))
        _setup_done = True
        logger.info("langgraph checkpoint schema is ready")


@asynccontextmanager
async def checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Open a checkpointer for the lifetime of a run.

    The schema is created by `ensure_schema()` at worker startup, not here.
    The lazy call below is a fallback for a process that never ran startup (the
    backend, or a test importing this directly); once the flag is set it costs
    nothing, and callers already inside a transaction are the case it must not
    be reached from.

    LangGraph's tables live outside Alembic on purpose: they are the library's
    schema, versioned with the library, and hand-managing them in our
    migrations would fight upgrades.
    """
    await ensure_schema()
    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn()) as saver:
        yield saver
