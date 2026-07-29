"""Audit recording — the single write path for the immutable trail.

Every tool call and every LLM call goes through here (spec 03 §6, G2.5).
Nothing else writes audit_log, so "did this get logged?" has one answer.

Secrets rule (spec 03 §1): provider credentials live in config and are never
tool arguments or logged prompts. `_scrub` is a belt-and-braces backstop that
redacts anything that looks like a credential before it reaches the database.
"""

import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

SECRET_KEY_HINTS = ("api_key", "apikey", "token", "secret", "password", "authorization", "dsn")
REDACTED = "[redacted]"


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if any(hint in str(key).lower() for hint in SECRET_KEY_HINTS)
                else _scrub(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value[:50]]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= 4000 else value[:4000] + "…[truncated]"
    return value


async def record(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID | None,
    actor: str,
    tool: str,
    payload: Any = None,
    result: Any = None,
    latency_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_estimate: float | None = None,
) -> None:
    session.add(
        AuditLog(
            org_id=org_id,
            run_id=run_id,
            actor=actor,
            tool=tool,
            payload=_scrub(payload),
            result=_scrub(result),
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_estimate=cost_estimate,
        )
    )
    await session.flush()


@asynccontextmanager
async def timed(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID | None,
    actor: str,
    tool: str,
    payload: Any = None,
) -> AsyncIterator[dict[str, Any]]:
    """Record one call, timed, whether it succeeds or raises.

    Yields a mutable dict the caller fills in (`result`, `tokens_in`,
    `tokens_out`, `cost_estimate`). A raised exception is logged as an error
    result and re-raised — a failed tool call is still an audited tool call.
    """
    started = time.monotonic()
    box: dict[str, Any] = {}
    try:
        yield box
    except Exception as exc:
        await record(
            session,
            org_id=org_id,
            run_id=run_id,
            actor=actor,
            tool=tool,
            payload=payload,
            result={"error": type(exc).__name__, "message": str(exc)[:500]},
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise
    else:
        await record(
            session,
            org_id=org_id,
            run_id=run_id,
            actor=actor,
            tool=tool,
            payload=payload,
            result=box.get("result"),
            latency_ms=int((time.monotonic() - started) * 1000),
            tokens_in=box.get("tokens_in"),
            tokens_out=box.get("tokens_out"),
            cost_estimate=box.get("cost_estimate"),
        )
