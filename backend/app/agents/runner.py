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
from sqlalchemy import and_, or_, select, update

from app.agents import audit
from app.agents.checkpointer import checkpointer, ensure_schema
from app.agents.graph import build_graph
from app.agents.prompts import AGENT_VERSION
from app.agents.tools import ToolContext
from app.config import get_settings
from app.db import async_session_factory
from app.ingestion.queue import enqueue_resume, enqueue_run
from app.logging_config import bind_run
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
from app.tenancy import get_scoped

logger = logging.getLogger(__name__)


async def execute_run(
    ctx: dict[str, Any], run_id: str, org_id: str, actor_user_id: str | None = None
) -> str:
    """arq entrypoint. Returns the terminal run status.

    `actor_user_id` is the human who triggered triage. Optional because
    recovery re-enqueues without one — a system-initiated retry has no human
    behind it, and saying so is more honest than inventing one.
    """
    run_uuid = uuid.UUID(run_id)
    org_uuid = uuid.UUID(org_id)
    settings = get_settings()

    # Before the session opens, never inside it. The checkpointer's schema
    # setup ends in CREATE INDEX CONCURRENTLY, which waits for every older
    # transaction — including the one this job is about to hold open for its
    # whole life. Normally a no-op; the worker did this at startup.
    await ensure_schema()

    # Every line emitted below carries this run id, here and in the API alike.
    # Correlating the two streams is the whole point: "what happened to run X?"
    # should be one query, not a timestamp-matching exercise across containers.
    bind_run(run_id, org_id)

    async with async_session_factory() as session:
        run = await get_scoped(session, Run, run_uuid, org_uuid)
        if run is None:
            logger.warning("run %s not found in org %s", run_id, org_id)
            return "missing"

        # Claim the run with a compare-and-swap, exactly as resume_run refuses
        # a duplicate resume. Checking id and org alone was not enough: a
        # redelivered or stale initial job found a *completed* run, set it back
        # to running, and drove it through the graph again — erasing
        # terminality and creating a second approval on a run a human had
        # already finished with (Codex Phase 4 finding 2).
        #
        # `queued` is always claimable. `running` is claimable only once it has
        # gone stale, because those are two different situations wearing the
        # same status: a run a worker is actively driving right now, and one
        # left behind by a worker that died. Accepting `running` outright let a
        # duplicate delivery re-enter the graph *alongside* the live job
        # (Codex Phase 4 residual finding 1); refusing it outright would strand
        # every crashed run forever. The cutoff is what separates them, and it
        # is the same cutoff recovery uses to decide a run needs re-enqueueing.
        #
        # Attempts increment inside the same UPDATE, so the count survives a
        # process that dies before writing anything else.
        stale = datetime.now(UTC) - timedelta(seconds=settings.run_timeout_seconds)
        claimed = await session.execute(
            update(Run)
            .where(
                Run.id == run_uuid,
                or_(
                    Run.status == RunStatus.queued,
                    and_(Run.status == RunStatus.running, Run.started_at < stale),
                ),
            )
            .values(
                status=RunStatus.running,
                attempts=Run.attempts + 1,
                started_at=datetime.now(UTC),
                agent_version=AGENT_VERSION,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 0:
            await session.rollback()
            await session.refresh(run)
            logger.info("execute: run %s already %s; ignoring", run_id, run.status.value)
            return run.status.value
        await session.commit()
        await session.refresh(run)

        if run.attempts > settings.max_run_attempts:
            return await _dead_letter(session, run)

        context = ToolContext(session=session, org_id=org_uuid, run_id=run_uuid, actor="agent")
        # An eval run uses the graph with no approval node and no execute node
        # (D19 decision 2). Selected from the run row, not from the job
        # payload: a payload can be forged or replayed, a column cannot be set
        # by whoever enqueued the job.
        is_eval = run.eval_batch_id is not None
        try:
            async with checkpointer() as saver:
                graph = build_graph(saver, eval_mode=is_eval)
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


async def resume_run(
    ctx: dict[str, Any], run_id: str, org_id: str, actor_user_id: str | None = None
) -> str:
    """arq entrypoint: continue a paused run after a human decision.

    This is deliberately a *fresh* job in a possibly different process. It
    loads the checkpoint written before the pause and continues from the
    interrupt — which is what makes the pause durable rather than a
    same-request wait (G3.1).
    """
    run_uuid = uuid.UUID(run_id)
    org_uuid = uuid.UUID(org_id)
    settings = get_settings()

    await ensure_schema()
    bind_run(run_id, org_id)

    async with async_session_factory() as session:
        run = await get_scoped(session, Run, run_uuid, org_uuid)
        if run is None:
            logger.warning("resume: run %s not found in org %s", run_id, org_id)
            return "missing"

        approval = (
            await session.execute(select(Approval).where(Approval.run_id == run.id))
        ).scalar_one_or_none()
        if approval is None or approval.decision is None:
            logger.warning("resume: run %s has no decided approval", run_id)
            return "missing"

        # Claim the resume, with the same stale-vs-active distinction the
        # initial job makes. `awaiting_approval` is always claimable — that run
        # is parked. `executing` means another resume is in flight, and only a
        # stale one may be taken over; the previous check accepted any
        # `executing` row, so a duplicate delivery could drive the write path
        # concurrently with the live job (Codex Phase 4 residual finding 1).
        #
        # Idempotency (G3.3) makes a *replayed* write safe, not a *concurrent*
        # one racing the ledger insert.
        stale = datetime.now(UTC) - timedelta(seconds=settings.run_timeout_seconds)
        claimed = await session.execute(
            update(Run)
            .where(
                Run.id == run_uuid,
                or_(
                    Run.status == RunStatus.awaiting_approval,
                    and_(Run.status == RunStatus.executing, Run.started_at < stale),
                ),
            )
            .values(status=RunStatus.executing, started_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 0:
            await session.rollback()
            await session.refresh(run)
            logger.info("resume: run %s already %s; ignoring", run_id, run.status.value)
            return run.status.value
        await session.commit()
        await session.refresh(run)

        resume_payload = {
            "decision": approval.decision.value,
            "final_values": approval.final_values,
        }
        context = ToolContext(
            session=session,
            org_id=org_uuid,
            run_id=run_uuid,
            # The payload's actor is the authority the API attached at
            # decision time; the approval row is the durable fallback for a
            # recovery re-enqueue, which carries none.
            actor=f"user:{actor_user_id or approval.approver_user_id}",
            # The single place a gated write is authorised: a decided approval
            # has just been loaded for this run.
            approval_granted=True,
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


async def reconcile_runs(ctx: dict[str, Any]) -> int:
    """Periodic reconciler (arq cron).

    Startup-only recovery is not enough: the outage that strands a decision
    need not involve the worker restarting at all. Redis can go away and come
    back while the worker stays up the whole time, so nothing ever re-reads the
    durable state. This runs on a schedule and makes Postgres — not the queue —
    the authority on what still needs doing.
    """
    return await recover_stranded_runs()


async def recover_stranded_runs() -> int:
    """Re-enqueue runs whose worker died mid-execute (spec 04 §4).

    A run left in `executing` has an approved decision and possibly a partly
    applied set of writes. Replay is safe precisely because each write claims
    its idempotency key first: the completed ones return their stored result
    and only the unfinished ones touch the adapter (G3.3).

    Also recovers runs left in `awaiting_approval` whose approval is already
    *decided*. The decision is committed before the resume is enqueued, so a
    queue outage in that window leaves an irreversible decision with nothing to
    act on it — and the approver cannot retry, because a second decision is
    correctly refused with 409. Waiting on a human is fine; waiting on a queue
    that already dropped the message is not.

    A run in `awaiting_approval` with a *pending* approval is untouched: that
    one really is waiting on a person, for as long as it takes.
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
                await enqueue_resume(run.id, run.org_id, started_at=run.started_at)

            # Decided-but-unresumed: the CAS committed, the enqueue did not.
            orphaned = (
                (
                    await session.execute(
                        select(Run)
                        .join(Approval, Approval.run_id == Run.id)
                        .where(
                            Run.status == RunStatus.awaiting_approval,
                            Approval.status == ApprovalStatus.decided,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for run in orphaned:
                logger.warning("recovering run %s: decided approval never resumed", run.id)
                await enqueue_resume(run.id, run.org_id, started_at=run.started_at)

            # Never-started and crashed-mid-triage. `queued` means the job is
            # gone — Redis restarted, evicted it, or the enqueue failed.
            # `running` means a worker claimed it and died before reaching any
            # terminal handler; a poison message that kills the process leaves
            # exactly this, and scanning only `executing` missed it entirely
            # (Codex Phase 4 finding 3). Neither state is waiting on a human.
            #
            # The two states age on different clocks, and using one for both
            # was wrong: a run *running* for two hours is stranded no matter
            # when it was created, while a run created two hours ago but
            # claimed a second ago is perfectly healthy. So `queued` is judged
            # on created_at (it has no start) and `running` on started_at.
            unfinished = (
                (
                    await session.execute(
                        select(Run).where(
                            or_(
                                and_(
                                    Run.status == RunStatus.queued,
                                    Run.created_at < cutoff,
                                ),
                                and_(
                                    Run.status == RunStatus.running,
                                    Run.started_at < cutoff,
                                ),
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            recovered = 0
            for run in unfinished:
                # The attempt that killed the worker was already counted, so a
                # run at the limit has had its chances. Waiting for a further
                # pickup to trip `_dead_letter` would wait forever: arq's own
                # max_tries is the same number, so there need not be one.
                if (run.attempts or 0) >= settings.max_run_attempts:
                    logger.warning("dead-lettering run %s: attempts exhausted", run.id)
                    await _dead_letter(session, run)
                    continue
                logger.warning("recovering run %s stranded in %s", run.id, run.status.value)
                await enqueue_run(run.id, run.org_id, started_at=run.started_at)
                recovered += 1

            return len(stranded) + len(orphaned) + recovered
    except Exception:  # noqa: BLE001 - recovery is best-effort housekeeping
        # A worker that refuses to start because a *recovery* query failed is
        # strictly worse than one that starts without recovering. This fires on
        # every cold stack: compose brings the worker up before migrations run,
        # so `runs` does not exist yet and the query raises UndefinedTableError.
        logger.warning("stranded-run recovery skipped", exc_info=True)
        return 0


async def _dead_letter(session: Any, run: Run) -> str:
    """Stop retrying a run that has exhausted its attempts (spec 05 §4).

    Terminal, and visible: it lands on the run detail page as a typed failure
    reason like any other, so a poisoned run is something an operator finds
    rather than something they notice missing. The alternative — leaving it on
    the queue — spends a worker slot per redelivery forever.
    """
    settings = get_settings()
    run.status = RunStatus.failed
    run.failure_reason = FailureReason.dead_letter
    run.error = (
        f"dead-lettered after {run.attempts} attempts "
        f"(max {settings.max_run_attempts}); the job was redelivered without "
        "ever completing"
    )
    run.finished_at = datetime.now(UTC)
    await session.commit()
    logger.error("run %s dead-lettered after %d attempts", run.id, run.attempts)
    await audit.record(
        org_id=run.org_id,
        run_id=run.id,
        actor="system:worker",
        tool="run.dead_letter",
        payload={"attempts": run.attempts, "max_attempts": settings.max_run_attempts},
        result={"status": RunStatus.failed.value},
    )
    return RunStatus.failed.value


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

    # Scoped by the run's own org. A run row can name a ticket in another
    # organization -- the foreign key covers ticket_id, not (org_id, ticket_id)
    # -- and finalization was mutating it: org B's ticket went from new to
    # actioned because org A's run completed (Codex Phase 4 residual finding 2).
    ticket = await get_scoped(session, Ticket, run.ticket_id, run.org_id)
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

    ticket = await get_scoped(session, Ticket, run.ticket_id, run.org_id)
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
