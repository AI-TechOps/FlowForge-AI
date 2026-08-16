"""Eval batch orchestration (spec 06 §2, D19 decision 4).

A batch is started by the API, executed by the worker, and scored as each run
settles. It deliberately reuses the ordinary run machinery — same arq queue,
same `execute_run`, same audit trail — so an eval measures the pipeline that
ships rather than a parallel one built to be measurable.

The only difference is the graph: eval runs use `build_graph(eval_mode=True)`,
which has no approval node, so a 20-ticket batch cannot strand 20 runs waiting
for a human (D19 decision 2).
"""

import json
import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_VERSION
from app.config import get_settings
from app.eval.judge import judge_result
from app.eval.scoring import is_grounded, retrieval_hit, score_fields, summarize
from app.ingestion.queue import enqueue_eval_batch
from app.logging_config import bind_org, run_context
from app.models import BatchStatus, EvalBatch, EvalResult, Run, RunStatus, Ticket

logger = logging.getLogger(__name__)

# How long the scorer waits between checks on a batch whose runs are still
# going. Long enough that a twenty-run batch costs a handful of jobs, short
# enough that a finished batch is recorded promptly.
EVAL_POLL_SECONDS = 10

# The repository layout, used when EVAL_LABELS_PATH is unset. Correct for a
# local checkout and wrong inside the image, where `fixtures/` is outside the
# build context — which is why the containers set the variable and mount the
# directory read-only.
REPO_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "eval_tickets.json"


class MissingLabels(RuntimeError):
    """The answer key is not where configuration says it is.

    Its own type so the API can turn it into an actionable 503 instead of a
    bare 500: "the labels are not mounted" is an operator instruction, and a
    stack trace is not.
    """


def labels_path() -> Path:
    configured = get_settings().eval_labels_path.strip()
    return Path(configured) if configured else REPO_FIXTURE


# A run that reached any of these has finished producing output, one way or
# another. `awaiting_approval` is absent on purpose: an eval run cannot reach
# it, and if one ever did that would be a bug worth surfacing rather than
# quietly scoring.
SETTLED = {RunStatus.completed, RunStatus.failed, RunStatus.rejected}


def load_labels() -> dict[str, dict[str, Any]]:
    """The answer key, read straight from the fixture.

    Deliberately not stored in `tickets`: the loader keeps labels out of the
    database precisely so the agent cannot see them (see load_eval_tickets.py).
    Reading them here keeps that property — the eval knows the answers, the
    pipeline never does.
    """
    path = labels_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MissingLabels(
            f"no eval answer key at {path}. Set EVAL_LABELS_PATH, or mount "
            "fixtures/ into the backend and worker containers as the compose "
            "file does."
        ) from exc
    return {record["id"]: record for record in data["eval_tickets"]}


async def score_run(
    session: AsyncSession,
    batch: EvalBatch,
    ticket: Ticket,
    run: Run | None,
    label: dict[str, Any],
) -> dict[str, Any]:
    """Score one settled run and persist its result row.

    Upserted on (batch_id, ticket_id), so re-scoring a batch overwrites rather
    than accumulates — which is what makes G5.1's "same batch re-scored gives
    identical accuracy" a statement about determinism.
    """
    settings = get_settings()
    actual = (run.output if run else None) or None
    evidence = (run.evidence if run else None) or []
    expected = label.get("labels", {})

    field_scores = score_fields(expected, actual)
    scores: dict[str, Any] = {
        name: {"expected": s.expected, "actual": s.actual, "correct": s.correct}
        for name, s in field_scores.items()
    }
    scores["grounded"] = is_grounded(actual, evidence)
    scores["retrieval_hit"] = retrieval_hit(label.get("grounding_references"), evidence)

    judge_model: str | None = None
    if actual:
        judgement = await judge_result(
            {"title": ticket.title, "description": ticket.description},
            actual,
            evidence,
            settings,
            org_id=batch.org_id,
            # Attributed to the run it judged, so the run detail page shows the
            # judgement alongside the work it scored rather than in a second
            # trail nobody opens.
            run_id=run.id if run else None,
        )
        if judgement is not None:
            scores["resolution_quality"] = judgement.resolution_quality
            scores["citation_support"] = judgement.citation_support
            scores["judge_rationale"] = judgement.rationale
            judge_model = settings.judge_model

    failure_reason = None
    if run is None:
        failure_reason = "not_started"
    elif run.failure_reason is not None:
        failure_reason = run.failure_reason.value
    elif actual is None:
        failure_reason = "no_output"

    row = {
        "id": uuid.uuid4(),
        "org_id": batch.org_id,
        "batch_id": batch.id,
        "run_id": run.id if run else None,
        "ticket_id": ticket.id,
        "seed_ref": ticket.external_ref,
        "expected": expected,
        "actual": actual,
        "scores": scores,
        "judge_model": judge_model,
        "failure_reason": failure_reason,
    }
    statement = insert(EvalResult).values(**row)
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_eval_results_batch_ticket",
            set_={
                "scores": statement.excluded.scores,
                "actual": statement.excluded.actual,
                "run_id": statement.excluded.run_id,
                "judge_model": statement.excluded.judge_model,
                "failure_reason": statement.excluded.failure_reason,
            },
        )
    )
    return {"scores": scores, "failure_reason": failure_reason}


async def finalize_batch(session: AsyncSession, batch: EvalBatch) -> dict[str, Any]:
    """Compute and store the batch summary.

    Written once, at the end, rather than derived on every read: a recorded
    batch must stay a fixed historical fact even after the scoring code
    changes, or the regression table compares numbers produced by two different
    scorers and calls the difference a regression (G5.5).
    """
    rows = (
        (await session.execute(select(EvalResult).where(EvalResult.batch_id == batch.id)))
        .scalars()
        .all()
    )
    summary = summarize([{"scores": r.scores, "failure_reason": r.failure_reason} for r in rows])
    batch.summary = summary
    batch.status = BatchStatus.completed
    batch.finished_at = datetime.now(UTC)
    await session.commit()
    logger.info(
        "eval batch %s complete: %s of %s scored, overall accuracy %s",
        batch.id,
        summary.get("scored_tickets"),
        summary.get("total_tickets"),
        summary.get("accuracy_overall"),
        # Carried as a field, not only inside the message, so the batch's lines
        # are queryable the way run_id makes a run's lines queryable.
        extra={"eval_batch_id": str(batch.id)},
    )
    return summary


def batch_payload(batch: EvalBatch) -> dict[str, Any]:
    return {
        "id": str(batch.id),
        "status": batch.status.value,
        "agent_version": batch.agent_version,
        "triage_model": batch.triage_model,
        "judge_model": batch.judge_model,
        "total_tickets": batch.total_tickets,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "summary": batch.summary,
        "created_at": batch.created_at.isoformat(),
    }


def result_payload(result: EvalResult) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "seed_ref": result.seed_ref,
        "ticket_id": str(result.ticket_id),
        "run_id": str(result.run_id) if result.run_id else None,
        "expected": result.expected,
        "actual": result.actual,
        "scores": result.scores,
        "judge_model": result.judge_model,
        "failure_reason": result.failure_reason,
    }


def batch_deadline(batch: EvalBatch) -> datetime:
    """When to stop waiting for a batch's runs and score what there is.

    Sized to the batch rather than to one run. `run_timeout_seconds + 60` was
    the whole budget, which is right for a single run and hopelessly short for
    twenty of them: at four concurrent workers, twenty real-model runs are five
    run-timeouts of work, so a real batch would have been cut off and every
    unfinished run scored as a failure — an eval reporting the queue depth as
    model accuracy.
    """
    settings = get_settings()
    concurrency = max(1, settings.worker_concurrency)
    waves = max(1, math.ceil(max(1, batch.total_tickets) / concurrency))
    started = batch.started_at or batch.created_at
    return started + timedelta(seconds=settings.run_timeout_seconds * waves + 120)


async def score_batch(ctx: dict[str, Any], batch_id: str, org_id: str, attempt: int = 0) -> str:
    """arq entrypoint: score a batch once its runs settle, else come back later.

    Checks and re-enqueues rather than sleeping in a loop. A long-lived polling
    job would outlive `job_timeout` on any real-model batch — arq would kill the
    scorer mid-wait and the batch would sit in `running` forever — and a job
    holding a database session for twenty minutes is the wrong shape besides.
    Re-enqueueing also means a worker restart costs one deferred job, not the
    scoring of the whole batch.

    Waiting rather than being driven by run completion is still deliberate: G5.4
    requires the batch to complete even when individual runs fail, and a
    completion callback would have to invent a story for the runs that never
    call back. A deadline plus "score whatever state each run is in" makes that
    trivially true.
    """
    from app.db import async_session_factory
    from app.tenancy import get_scoped

    batch_uuid = uuid.UUID(batch_id)
    org_uuid = uuid.UUID(org_id)
    bind_org(org_id)

    async with async_session_factory() as session:
        batch = await get_scoped(session, EvalBatch, batch_uuid, org_uuid)
        if batch is None:
            logger.warning("eval batch %s not found in org %s", batch_id, org_id)
            return "missing"
        if batch.status is not BatchStatus.running:
            # Already finalized. A redelivered job must not re-open a recorded
            # batch, or the regression table gains a second version of a row
            # that was supposed to be history.
            return batch.status.value

        try:
            labels = load_labels()
        except MissingLabels:
            # The API refuses to start a batch without the labels, so reaching
            # here means they went missing between start and scoring. Mark the
            # batch failed rather than leaving it running forever: a batch that
            # never settles is worse than one that says why it stopped.
            batch.status = BatchStatus.failed
            batch.finished_at = datetime.now(UTC)
            await session.commit()
            logger.exception("eval batch %s cannot be scored", batch_id)
            return "missing_labels"

        try:
            runs = (
                (
                    await session.execute(
                        select(Run)
                        .where(Run.eval_batch_id == batch_uuid, Run.org_id == org_uuid)
                        # Overwrite the identity map's copies instead of
                        # serving rows the worker has since updated. NOT
                        # `session.expire_all()`, which also expires the
                        # batch — and reading an expired attribute of it
                        # afterwards is a synchronous lazy load, which on
                        # asyncpg raises MissingGreenlet and leaves the
                        # batch stuck in `running` forever.
                        .execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
            unsettled = [r for r in runs if r.status not in SETTLED]
            if unsettled and datetime.now(UTC) < batch_deadline(batch):
                await enqueue_eval_batch(
                    batch_uuid, org_uuid, attempt=attempt + 1, defer_seconds=EVAL_POLL_SECONDS
                )
                logger.info(
                    "eval batch %s: %s of %s runs still going; checking again in %ss",
                    batch_id,
                    len(unsettled),
                    len(runs),
                    EVAL_POLL_SECONDS,
                    extra={"eval_batch_id": batch_id},
                )
                return "waiting"

            for run in runs:
                ticket = await get_scoped(session, Ticket, run.ticket_id, org_uuid)
                if ticket is None:
                    continue
                label = labels.get(ticket.external_ref or "")
                if label is None:
                    continue
                # Scoped rather than bound: scoring walks many runs in one job,
                # and the batch-level lines after this loop belong to the batch,
                # not to whichever run happened to be scored last.
                with run_context(str(run.id), org_id):
                    await score_run(session, batch, ticket, run, label)
            await session.commit()

            summary = await finalize_batch(session, batch)
            return str(summary.get("accuracy_overall"))
        except Exception:  # noqa: BLE001 - a batch must always reach a terminal state
            # G5.4 asks for a batch that completes even when things go wrong.
            # An unhandled error here used to leave `running` on the row
            # forever, which is indistinguishable from a batch still working —
            # so a reader cannot tell a slow eval from a broken one.
            logger.exception("eval batch %s failed while scoring", batch_id)
            await session.rollback()
            # Re-read: after a rollback the loaded instance is expired, and
            # touching an expired attribute is the very lazy load that brought
            # us here.
            batch = await get_scoped(session, EvalBatch, batch_uuid, org_uuid)
            if batch is not None:
                batch.status = BatchStatus.failed
                batch.finished_at = datetime.now(UTC)
                await session.commit()
            return "failed"


def new_batch(org_id: uuid.UUID, total: int) -> EvalBatch:
    settings = get_settings()
    return EvalBatch(
        org_id=org_id,
        agent_version=AGENT_VERSION,
        triage_model=settings.triage_model,
        judge_model=settings.judge_model,
        status=BatchStatus.running,
        total_tickets=total,
        started_at=datetime.now(UTC),
    )
