"""Run execution: the arq job that drives one triage run to a terminal state.

Reliability controls (spec 03 §6) live here rather than in the graph so the
graph stays a pure description of the workflow: per-run timeout, terminal
status transitions, and typed failure reasons. A run that starts always ends
in a terminal status — never stuck in `running`.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.agents.checkpointer import checkpointer
from app.agents.graph import build_graph
from app.agents.prompts import AGENT_VERSION
from app.agents.tools import ToolContext
from app.config import get_settings
from app.db import async_session_factory
from app.models import FailureReason, Run, RunStatus, Ticket, TicketStatus

logger = logging.getLogger(__name__)


async def execute_run(ctx: dict[str, Any], run_id: str, org_id: str) -> str:
    """arq entrypoint. Returns the terminal run status."""
    run_uuid = uuid.UUID(run_id)
    org_uuid = uuid.UUID(org_id)
    settings = get_settings()

    async with async_session_factory() as session:
        run = await session.get(Run, run_uuid)
        if run is None or run.org_id != org_uuid:
            logger.warning("run %s not found in org %s", run_id, org_id)
            return "missing"

        run.status = RunStatus.running
        run.started_at = datetime.now(UTC)
        run.agent_version = AGENT_VERSION
        await session.commit()

        context = ToolContext(
            session=session, org_id=org_uuid, run_id=run_uuid, actor="agent"
        )
        try:
            async with checkpointer() as saver:
                graph = build_graph(saver)
                state = await asyncio.wait_for(
                    graph.ainvoke(
                        {"ticket_id": str(run.ticket_id)},
                        config={
                            "configurable": {
                                "thread_id": str(run_uuid),
                                "tool_context": context,
                            }
                        },
                    ),
                    timeout=settings.run_timeout_seconds,
                )
        except TimeoutError:
            return await _fail(
                session,
                run,
                FailureReason.timeout,
                f"run exceeded {settings.run_timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 - any escape must still land terminal
            logger.exception("run %s failed", run_id)
            return await _fail(session, run, FailureReason.internal_error, str(exc))

        return await _finalize(session, run, state)


async def _finalize(session: Any, run: Run, state: dict[str, Any]) -> str:
    run.evidence = state.get("evidence")

    reason = state.get("failure_reason")
    if reason is not None:
        return await _fail(session, run, FailureReason(reason), state.get("error"))

    result = state.get("result")
    if result is None:
        # Defensive: a graph path that produced neither result nor reason is a
        # bug, and a run must never report success without output.
        return await _fail(
            session, run, FailureReason.internal_error, "graph produced no result"
        )

    run.status = RunStatus.completed
    run.output = result
    run.confidence = state.get("confidence")
    run.finished_at = datetime.now(UTC)

    ticket = await session.get(Ticket, run.ticket_id)
    if ticket is not None and ticket.status == TicketStatus.new:
        ticket.status = TicketStatus.triaged

    await session.commit()
    return RunStatus.completed.value


async def _fail(session: Any, run: Run, reason: FailureReason, error: str | None) -> str:
    await session.rollback()
    run = await session.merge(run)
    run.status = RunStatus.failed
    run.failure_reason = reason
    run.error = (error or "")[:2000]
    run.finished_at = datetime.now(UTC)
    await session.commit()
    logger.info("run %s failed: %s", run.id, reason.value)
    return RunStatus.failed.value
