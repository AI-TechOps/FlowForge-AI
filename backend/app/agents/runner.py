"""Run execution: the arq job that drives one triage run to a terminal state.

Reliability controls (spec 03 §6) live here rather than in the graph so the
graph stays a pure description of the workflow: per-run timeout, terminal
status transitions, and typed failure reasons. A run that starts always ends
in a terminal status — never stuck in `running`.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.types import Command
from sqlalchemy import select

from app.agents.checkpointer import checkpointer
from app.agents.graph import build_graph
from app.agents.prompts import AGENT_VERSION
from app.agents.tools import ToolContext
from app.config import get_settings
from app.db import async_session_factory
from app.ingestion.queue import enqueue_resume
from app.models import (
    Approval,
    ApprovalStatus,
    FailureReason,
    RiskClass,
    Run,
    RunStatus,
    Ticket,
    TicketStatus,
)

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

        context = ToolContext(session=session, org_id=org_uuid, run_id=run_uuid, actor="agent")
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


async def resume_run(ctx: dict[str, Any], run_id: str, org_id: str) -> str:
    """arq entrypoint: continue a paused run after a human decision.

    This is deliberately a *fresh* job in a possibly different process. It
    loads the checkpoint written before the pause and continues from the
    interrupt — which is what makes the pause durable rather than a
    same-request wait (G3.1).
    """
    run_uuid = uuid.UUID(run_id)
    org_uuid = uuid.UUID(org_id)
    settings = get_settings()

    async with async_session_factory() as session:
        run = await session.get(Run, run_uuid)
        if run is None or run.org_id != org_uuid:
            logger.warning("resume: run %s not found in org %s", run_id, org_id)
            return "missing"

        approval = (
            await session.execute(select(Approval).where(Approval.run_id == run.id))
        ).scalar_one_or_none()
        if approval is None or approval.decision is None:
            logger.warning("resume: run %s has no decided approval", run_id)
            return "missing"

        # Terminal runs are never resumed: a duplicate resume job must be a
        # no-op rather than a second pass at the write path.
        if run.status not in (RunStatus.awaiting_approval, RunStatus.executing):
            logger.info("resume: run %s already %s", run_id, run.status.value)
            return run.status.value

        run.status = RunStatus.executing
        await session.commit()

        resume_payload = {
            "decision": approval.decision.value,
            "final_values": approval.final_values,
        }
        context = ToolContext(
            session=session,
            org_id=org_uuid,
            run_id=run_uuid,
            actor=f"user:{approval.approver_user_id}",
        )
        try:
            async with checkpointer() as saver:
                graph = build_graph(saver)
                state = await asyncio.wait_for(
                    graph.ainvoke(
                        Command(resume=resume_payload),
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
                f"resume exceeded {settings.run_timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 - any escape must still land terminal
            logger.exception("resume of run %s failed", run_id)
            return await _fail(session, run, FailureReason.tool_error, str(exc))

        return await _finalize_decision(session, run, state)


async def recover_stranded_runs() -> int:
    """Re-enqueue runs whose worker died mid-execute (spec 04 §4).

    A run left in `executing` has an approved decision and possibly a partly
    applied set of writes. Replay is safe precisely because each write claims
    its idempotency key first: the completed ones return their stored result
    and only the unfinished ones touch the adapter (G3.3).

    Runs in `awaiting_approval` are deliberately NOT recovered — they are
    waiting on a human, not on us, and that wait is allowed to be arbitrarily
    long. That is the difference between a stalled run and a paused one.
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.run_timeout_seconds)

    try:
        async with async_session_factory() as session:
            stranded = (
                (
                    await session.execute(
                        select(Run).where(
                            Run.status == RunStatus.executing, Run.started_at < cutoff
                        )
                    )
                )
                .scalars()
                .all()
            )
            for run in stranded:
                logger.warning("recovering run %s stranded in executing", run.id)
                await enqueue_resume(run.id, run.org_id)
            return len(stranded)
    except Exception:  # noqa: BLE001 - recovery is best-effort housekeeping
        # A worker that refuses to start because a *recovery* query failed is
        # strictly worse than one that starts without recovering. This fires on
        # every cold stack: compose brings the worker up before migrations run,
        # so `runs` does not exist yet and the query raises UndefinedTableError.
        logger.warning("stranded-run recovery skipped", exc_info=True)
        return 0


async def _finalize_decision(session: Any, run: Run, state: dict[str, Any]) -> str:
    """Land a resumed run in its terminal status."""
    if state.get("rejected"):
        run.status = RunStatus.rejected
        run.finished_at = datetime.now(UTC)
        await session.commit()
        logger.info("run %s rejected — no write occurred", run.id)
        return RunStatus.rejected.value

    run.status = RunStatus.completed
    run.finished_at = datetime.now(UTC)
    output = dict(run.output or {})
    output["executed_actions"] = state.get("executed_actions", [])
    run.output = output

    ticket = await session.get(Ticket, run.ticket_id)
    if ticket is not None:
        ticket.status = TicketStatus.actioned

    await session.commit()
    logger.info(
        "run %s completed with %d action(s)", run.id, len(state.get("executed_actions", []))
    )
    return RunStatus.completed.value


async def _pause_for_approval(session: Any, run: Run, state: dict[str, Any]) -> str:
    """The graph interrupted: record the pending approval and stop.

    The job ends here. Nothing polls, nothing blocks — the checkpoint in
    Postgres is the only thing keeping the run alive, which is exactly what
    makes the pause survive a restart (D8, G3.1).
    """
    run.evidence = state.get("evidence")
    run.output = state.get("result")
    run.confidence = state.get("confidence")
    run.status = RunStatus.awaiting_approval

    existing = (
        await session.execute(select(Approval).where(Approval.run_id == run.id))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Approval(
                org_id=run.org_id,
                run_id=run.id,
                status=ApprovalStatus.pending,
                original_proposal=state.get("proposed_actions", []),
                risk_class=RiskClass(state.get("risk_class", RiskClass.low.value)),
            )
        )
    await session.commit()
    logger.info("run %s awaiting approval", run.id)
    return RunStatus.awaiting_approval.value


async def _finalize(session: Any, run: Run, state: dict[str, Any]) -> str:
    if state.get("__interrupt__"):
        return await _pause_for_approval(session, run, state)

    evidence = state.get("evidence")

    reason = state.get("failure_reason")
    if reason is not None:
        # A failed run keeps what it retrieved: "the model cited nothing from
        # these five chunks" is the whole diagnosis, and it is gone if the
        # evidence dies with the rollback.
        return await _fail(session, run, FailureReason(reason), state.get("error"), evidence)

    run.evidence = evidence

    result = state.get("result")
    if result is None:
        # Defensive: a graph path that produced neither result nor reason is a
        # bug, and a run must never report success without output.
        return await _fail(session, run, FailureReason.internal_error, "graph produced no result")

    run.status = RunStatus.completed
    run.output = result
    run.confidence = state.get("confidence")
    run.finished_at = datetime.now(UTC)

    ticket = await session.get(Ticket, run.ticket_id)
    if ticket is not None and ticket.status == TicketStatus.new:
        ticket.status = TicketStatus.triaged

    await session.commit()
    return RunStatus.completed.value


async def _fail(
    session: Any,
    run: Run,
    reason: FailureReason,
    error: str | None,
    evidence: list[dict[str, Any]] | None = None,
) -> str:
    # The rollback discards whatever the run wrote before it failed, so
    # anything worth keeping is re-applied after the merge below.
    await session.rollback()
    run = await session.merge(run)
    if evidence is not None:
        run.evidence = evidence
    run.status = RunStatus.failed
    run.failure_reason = reason
    run.error = (error or "")[:2000]
    run.finished_at = datetime.now(UTC)
    await session.commit()
    logger.info("run %s failed: %s", run.id, reason.value)
    return RunStatus.failed.value
