"""Metrics, audit and agent configuration (spec 06 §3).

One endpoint feeds the whole Phase 6 dashboard. The metric list here is copied
from the MVP spec deliberately — if this drifts, Phase 6 either renders
something nobody asked for or asks for something that does not exist.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_VERSION
from app.agents.taxonomy import Category, Priority, Team, Urgency
from app.auth.principal import ADMIN_ONLY, ANY_PERSONA, Principal
from app.config import get_settings
from app.db import get_session
from app.eval.prompts import JUDGE_VERSION
from app.llm.cost import PRICING_AS_OF
from app.models import (
    Approval,
    ApprovalStatus,
    AuditLog,
    Decision,
    EvalBatch,
    Role,
    Run,
    RunStatus,
)

router = APIRouter()

# Metrics an operator or approver does not see (D19 decision 6). Spend and
# model accuracy are oversight figures; the personas doc gives oversight to the
# Administrator.
ADMIN_ONLY_METRICS = ("estimated_cost_usd", "evaluation_accuracy", "avg_tokens_per_run")

# Audit rows that are tool calls, for the tool-success denominator. Expressed
# as "not a model call and not a lifecycle record" rather than as a list of the
# five tool names: a sixth tool should count the day it is added, whereas a new
# `llm.` or `run.` record should never silently join the denominator.
_NON_TOOL_PREFIXES = ("llm.", "run.", "approval.")
_TOOL_ROWS = tuple(AuditLog.tool.not_like(f"{prefix}%") for prefix in _NON_TOOL_PREFIXES)


@router.get("/api/metrics/summary")
async def metrics_summary(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ANY_PERSONA,
    window_days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """Every MVP dashboard metric, over a time window.

    Rates are `None` when their denominator is zero, never 0.0 — the same rule
    the eval scorer follows. A dashboard reading "0% approval rate" when nothing
    has been approved yet is actively misleading, and this is the number a
    stakeholder looks at first.
    """
    org_id = principal.org_id
    since = datetime.now(UTC) - timedelta(days=window_days)
    run_window = (Run.org_id == org_id, Run.created_at >= since)

    status_rows = (
        await session.execute(
            select(Run.status, func.count(Run.id)).where(*run_window).group_by(Run.status)
        )
    ).all()
    by_status = {status.value: count for status, count in status_rows}
    total_runs = sum(by_status.values())

    latency = (
        await session.execute(
            select(
                func.avg(cast(func.extract("epoch", Run.finished_at - Run.started_at), Float))
            ).where(*run_window, Run.finished_at.is_not(None), Run.started_at.is_not(None))
        )
    ).scalar()

    audit_window = (AuditLog.org_id == org_id, AuditLog.created_at >= since)
    tokens, cost = (
        await session.execute(
            select(
                func.sum(AuditLog.tokens_in + AuditLog.tokens_out),
                func.sum(AuditLog.cost_estimate),
            ).where(*audit_window)
        )
    ).one()

    # Tool success: an audit row whose result records an error is a failure.
    # Counted from the trail rather than from run status because a run can
    # succeed with a tool having failed and been retried (G3.6).
    #
    # Only the five MVP tools count. The trail also carries model calls
    # (`llm.*`) and lifecycle records (`run.*`, `approval.*`), and folding
    # those in would make "tool success rate" mean "share of audit rows that
    # did not error" — a different number that moves when logging changes.
    tool_total, tool_failed = (
        await session.execute(
            select(
                func.count(AuditLog.id),
                func.count(AuditLog.id).filter(AuditLog.result["error"].astext.is_not(None)),
            ).where(*audit_window, *_TOOL_ROWS)
        )
    ).one()

    decision_rows = (
        await session.execute(
            select(Approval.decision, func.count(Approval.id))
            .where(
                Approval.org_id == org_id,
                Approval.created_at >= since,
                Approval.status == ApprovalStatus.decided,
            )
            .group_by(Approval.decision)
        )
    ).all()
    decisions = {d.value: c for d, c in decision_rows if d is not None}
    decided = sum(decisions.values())

    latest_batch = (
        await session.execute(
            select(EvalBatch)
            .where(EvalBatch.org_id == org_id, EvalBatch.summary.is_not(None))
            .order_by(EvalBatch.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    batch_summary = (latest_batch.summary if latest_batch else None) or {}

    payload: dict[str, Any] = {
        "window_days": window_days,
        "total_runs": total_runs,
        "successful_runs": by_status.get(RunStatus.completed.value, 0),
        "failed_runs": by_status.get(RunStatus.failed.value, 0),
        "waiting_approvals": by_status.get(RunStatus.awaiting_approval.value, 0),
        "avg_latency_seconds": round(float(latency), 2) if latency is not None else None,
        "avg_tokens_per_run": _ratio(int(tokens or 0), total_runs, digits=1),
        "tool_success_rate": _ratio(
            int(tool_total or 0) - int(tool_failed or 0), int(tool_total or 0)
        ),
        "approval_rate": _ratio(decisions.get(Decision.approved.value, 0), decided),
        "human_edit_rate": _ratio(decisions.get(Decision.edited.value, 0), decided),
        "human_rejection_rate": _ratio(decisions.get(Decision.rejected.value, 0), decided),
        "evaluation_accuracy": batch_summary.get("accuracy_overall"),
        "retrieval_success": batch_summary.get("retrieval_hit_at_k"),
        "grounded_rate": batch_summary.get("grounded_rate"),
        "estimated_cost_usd": round(float(cost or 0.0), 6),
        "cost_pricing_as_of": PRICING_AS_OF,
        "latest_eval_batch_id": str(latest_batch.id) if latest_batch else None,
    }

    if not principal.has_any(Role.administrator):
        # Removed, not zeroed. A zero would be a lie an operator could act on;
        # an absent key is a fact the dashboard can render as "not available".
        for key in ADMIN_ONLY_METRICS:
            payload.pop(key, None)
        payload.pop("cost_pricing_as_of", None)
    return payload


@router.get("/api/audit")
async def list_audit(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
    run_id: uuid.UUID | None = Query(default=None),
    actor: str | None = Query(default=None, max_length=100),
    tool: str | None = Query(default=None, max_length=100),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """The cross-run audit view (Phase 6's Audit log screen).

    Paginated with a hard ceiling: an unbounded audit query is the one endpoint
    guaranteed to grow without limit, and the trail is worth more if reading it
    cannot take the database down.
    """
    filters = [AuditLog.org_id == principal.org_id]
    if run_id is not None:
        filters.append(AuditLog.run_id == run_id)
    if actor:
        filters.append(AuditLog.actor == actor)
    if tool:
        filters.append(AuditLog.tool == tool)
    if since is not None:
        filters.append(AuditLog.created_at >= since)
    if until is not None:
        filters.append(AuditLog.created_at <= until)

    total = (await session.execute(select(func.count(AuditLog.id)).where(*filters))).scalar_one()
    entries = (
        (
            await session.execute(
                select(AuditLog)
                .where(*filters)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [
            {
                "id": str(entry.id),
                "run_id": str(entry.run_id) if entry.run_id else None,
                "actor": entry.actor,
                "tool": entry.tool,
                "payload": entry.payload,
                "result": entry.result,
                "latency_ms": entry.latency_ms,
                "tokens_in": entry.tokens_in,
                "tokens_out": entry.tokens_out,
                "cost_estimate": entry.cost_estimate,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in entries
        ],
    }


@router.get("/api/config/agent")
async def agent_config(principal: Principal = ANY_PERSONA) -> dict[str, Any]:
    """Read-only agent configuration — the MVP's configuration page.

    Read-only on purpose: CLAUDE.md is explicit that agent configuration lives
    in code and database records, not a drag-and-drop builder. This shows what
    is running; changing it is a commit.
    """
    settings = get_settings()
    return {
        "agent_version": AGENT_VERSION,
        "judge_version": JUDGE_VERSION,
        "llm_provider": settings.llm_provider,
        "triage_model": settings.triage_model,
        "judge_model": settings.judge_model,
        "embedding_model": settings.embedding_model,
        "run_timeout_seconds": settings.run_timeout_seconds,
        "max_run_attempts": settings.max_run_attempts,
        # The allowed enums, served from the same source the validator uses —
        # a config page showing a taxonomy the agent does not actually enforce
        # would be worse than no config page.
        "taxonomy": {
            "categories": [m.value for m in Category],
            "urgencies": [m.value for m in Urgency],
            "teams": [m.value for m in Team],
            "priorities": [m.value for m in Priority],
        },
    }


def _ratio(numerator: int, denominator: int, digits: int = 4) -> float | None:
    """None for an empty denominator — see the module docstring."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, digits)
