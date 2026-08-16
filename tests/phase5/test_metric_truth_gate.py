"""G5.3 — every dashboard metric verified against a hand-computed value.

A known dataset is written straight into a fresh tenant: 5 runs, 5 approvals,
a fixed audit trail and one recorded eval batch. Every figure this file asserts
was computed on paper first and is spelled out in `EXPECTED` below, so a
reviewer can check the endpoint against arithmetic rather than against the
endpoint's own SQL.

Rows are inserted directly rather than driven through the pipeline on purpose:
the point is to fix the inputs exactly. A dataset produced by running the agent
would move whenever the agent moved, and then a metric bug and a model change
would look identical.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from .conftest import Phase5Client, Tenant, connect, detail, new_tenant

# ---------------------------------------------------------------------------
# The dataset, and the arithmetic it implies.
#
# runs:      3 completed, 1 failed, 1 awaiting_approval          -> 5 total
# latency:   the 3 completed ran 2s, 4s and 6s                   -> mean 4.0
# approvals: 2 approved, 1 edited, 1 rejected decided, 1 pending -> 4 decided
# audit:     4 tool rows, one an error                           -> 3/4 success
#            + llm.classify and llm.judge rows (200 tokens, $0.003)
#            + a run.dead_letter error row, which is NOT a tool
# eval:      one completed batch, accuracy 0.8, hit@k 0.6, grounded 0.9
# ---------------------------------------------------------------------------
EXPECTED: dict[str, Any] = {
    "total_runs": 5,
    "successful_runs": 3,
    "failed_runs": 1,
    "waiting_approvals": 1,
    "avg_latency_seconds": 4.0,
    "avg_tokens_per_run": 40.0,  # 200 tokens over 5 runs
    "tool_success_rate": 0.75,  # 3 of 4 tool calls, model/lifecycle rows excluded
    "approval_rate": 0.5,  # 2 of 4 decisions
    "human_edit_rate": 0.25,
    "human_rejection_rate": 0.25,
    "evaluation_accuracy": 0.8,
    "retrieval_success": 0.6,
    "grounded_rate": 0.9,
    "estimated_cost_usd": 0.003,
}

# Removed entirely for non-administrators (D19 decision 6) — spend and model
# accuracy are oversight figures, and the personas doc gives oversight to the
# Administrator.
#
# `avg_tokens_per_run` was listed here and should not have been: spec 06 §3
# names tokens among the metrics every authenticated role sees. Corrected on
# Codex's own instruction in the Phase 5 adversarial review (finding 6), which
# flagged this assertion as encoding the runtime defect rather than catching it.
ADMIN_ONLY_KEYS = ("estimated_cost_usd", "evaluation_accuracy")


async def _seed_metrics_dataset(database_url: str, org_id: str) -> None:
    org = UUID(org_id)
    now = datetime.now(UTC)
    connection = await connect(database_url)
    try:
        ticket_id = uuid4()
        await connection.execute(
            """
            INSERT INTO tickets (id, org_id, title, description, status, internal_notes)
            VALUES ($1, $2, 'G5.3 metric fixture', 'known dataset', 'new', '[]'::jsonb)
            """,
            ticket_id,
            org,
        )

        runs: list[tuple[UUID, str, int | None]] = [
            (uuid4(), "completed", 2),
            (uuid4(), "completed", 4),
            (uuid4(), "completed", 6),
            (uuid4(), "failed", None),
            (uuid4(), "awaiting_approval", None),
        ]
        for run_id, status, seconds in runs:
            started = now - timedelta(minutes=5)
            await connection.execute(
                """
                INSERT INTO runs (
                    id, org_id, ticket_id, status, agent_version, attempts,
                    started_at, finished_at, created_at
                )
                VALUES ($1, $2, $3, $4::run_status, 'triage-v1', 1, $5, $6, $7)
                """,
                run_id,
                org,
                ticket_id,
                status,
                started if seconds is not None else None,
                started + timedelta(seconds=seconds) if seconds is not None else None,
                now,
            )

        # One run created outside every sensible window, to prove the window
        # filter is real: it must not appear at window_days=30 and must appear
        # at window_days=365.
        await connection.execute(
            """
            INSERT INTO runs (
                id, org_id, ticket_id, status, agent_version, attempts, created_at
            )
            VALUES ($1, $2, $3, 'completed'::run_status, 'triage-v0', 1, $4)
            """,
            uuid4(),
            org,
            ticket_id,
            now - timedelta(days=200),
        )

        decisions = ["approved", "approved", "edited", "rejected"]
        for (run_id, _status, _seconds), decision in zip(runs, decisions, strict=False):
            await connection.execute(
                """
                INSERT INTO approvals (
                    id, org_id, run_id, status, decision, original_proposal,
                    risk_class, decided_at, created_at
                )
                VALUES (
                    $1, $2, $3, 'decided'::approval_status, $4::approval_decision,
                    '[]'::jsonb, 'medium'::risk_class, $5, $5
                )
                """,
                uuid4(),
                org,
                run_id,
                decision,
                now,
            )
        # A pending approval, which is not a decision and must not enter the
        # denominator of the approve/edit/reject rates.
        await connection.execute(
            """
            INSERT INTO approvals (
                id, org_id, run_id, status, original_proposal, risk_class, created_at
            )
            VALUES ($1, $2, $3, 'pending'::approval_status, '[]'::jsonb,
                    'medium'::risk_class, $4)
            """,
            uuid4(),
            org,
            runs[4][0],
            now,
        )

        audit_rows = [
            # (tool, result, tokens_in, tokens_out, cost)
            ("search_company_knowledge", '{"chunks": 5}', None, None, None),
            ("get_ticket", '{"ok": true}', None, None, None),
            ("assign_ticket", '{"ok": true}', None, None, None),
            (
                "change_ticket_priority",
                '{"error": "adapter timeout"}',
                None,
                None,
                None,
            ),
            ("llm.classify", '{"model": "fake:llama"}', 100, 50, 0.002),
            ("llm.judge", '{"model": "fake:qwen"}', 30, 20, 0.001),
            # Lifecycle records, not tool calls. An error here must not drag
            # tool success down — the metric would then mean "share of audit
            # rows that did not error", which moves whenever logging changes.
            (
                "run.dead_letter",
                '{"error": "gave up after 3 attempts"}',
                None,
                None,
                None,
            ),
            ("approval.decision", '{"decision": "approved"}', None, None, None),
        ]
        for tool, result, tokens_in, tokens_out, cost in audit_rows:
            await connection.execute(
                """
                INSERT INTO audit_log (
                    id, org_id, run_id, actor, tool, payload, result,
                    latency_ms, tokens_in, tokens_out, cost_estimate, created_at
                )
                VALUES ($1, $2, $3, 'agent', $4, '{}'::jsonb, $5::jsonb, 10, $6, $7, $8, $9)
                """,
                uuid4(),
                org,
                runs[0][0],
                tool,
                result,
                tokens_in,
                tokens_out,
                cost,
                now,
            )

        await connection.execute(
            """
            INSERT INTO eval_batches (
                id, org_id, agent_version, triage_model, judge_model, status,
                total_tickets, started_at, finished_at, summary, created_at
            )
            VALUES ($1, $2, 'triage-v1', 'fake:triage', 'fake:judge',
                    'completed'::eval_batch_status, 20, $3, $3, $4::jsonb, $3)
            """,
            uuid4(),
            org,
            now,
            '{"accuracy_overall": 0.8, "retrieval_hit_at_k": 0.6, "grounded_rate": 0.9}',
        )
    finally:
        await connection.close()


@pytest.fixture(scope="module")
def metrics_tenant(phase5_client: Phase5Client, phase5_database_url: str) -> Tenant:
    tenant = new_tenant(phase5_client, phase5_database_url)
    asyncio.run(_seed_metrics_dataset(phase5_database_url, tenant.org_id))
    return tenant


@pytest.fixture(scope="module")
def summary(phase5_client: Phase5Client, metrics_tenant: Tenant) -> dict[str, Any]:
    response = phase5_client.request(
        "GET", "/api/metrics/summary?window_days=30", token=metrics_tenant.admin
    )
    assert response.status == 200, detail(response)
    assert isinstance(response.body, dict), response.body
    return response.body


@pytest.mark.parametrize("metric", sorted(EXPECTED))
def test_g5_3_each_metric_matches_the_hand_computed_value(
    summary: dict[str, Any], metric: str
) -> None:
    assert summary[metric] == pytest.approx(EXPECTED[metric], abs=1e-6), (
        f"{metric} is {summary[metric]!r}, hand-computed {EXPECTED[metric]!r}; full={summary!r}"
    )


def test_g5_3_every_mvp_dashboard_metric_is_present() -> None:
    """The list is copied verbatim from the MVP spec.

    Phase 6 consumes this endpoint unchanged, so a missing key is a screen that
    cannot be built rather than a cosmetic omission.
    """
    # Deliberately re-stated rather than derived from EXPECTED: this asserts the
    # contract, EXPECTED asserts the arithmetic.
    required = {
        "total_runs",
        "successful_runs",
        "failed_runs",
        "waiting_approvals",
        "avg_latency_seconds",
        "avg_tokens_per_run",
        "tool_success_rate",
        "approval_rate",
        "human_edit_rate",
        "human_rejection_rate",
        "evaluation_accuracy",
        "retrieval_success",
        "estimated_cost_usd",
    }
    assert required <= set(EXPECTED), sorted(required - set(EXPECTED))


def test_g5_3_the_time_window_actually_filters(
    phase5_client: Phase5Client, metrics_tenant: Tenant
) -> None:
    wide = phase5_client.request(
        "GET", "/api/metrics/summary?window_days=365", token=metrics_tenant.admin
    )
    assert wide.status == 200, detail(wide)
    assert wide.body["total_runs"] == EXPECTED["total_runs"] + 1, (
        "a 200-day-old run is missing from a 365-day window; the window is not being applied"
    )


def test_g5_3_empty_denominators_report_none_rather_than_zero(
    phase5_client: Phase5Client, phase5_database_url: str
) -> None:
    """A fresh tenant has no data, and "no data" is not "0%".

    This is the number a stakeholder looks at first; a dashboard reading
    "0% approval rate" before anything has been approved is actively
    misleading.
    """
    fresh = new_tenant(phase5_client, phase5_database_url)
    response = phase5_client.request("GET", "/api/metrics/summary", token=fresh.admin)
    assert response.status == 200, detail(response)
    body = response.body
    assert body["total_runs"] == 0
    for key in (
        "approval_rate",
        "human_edit_rate",
        "tool_success_rate",
        "avg_latency_seconds",
    ):
        assert body[key] is None, f"{key} reports {body[key]!r} for an empty tenant"


def test_g5_3_cost_is_labelled_an_estimate_with_an_as_of_date(
    summary: dict[str, Any],
) -> None:
    """Pricing is versioned in code with an as-of date (D19 decision 7).

    The cost figure is the one most likely to be quoted out loud in a demo, so
    the date it was priced travels with it.
    """
    assert summary["cost_pricing_as_of"], summary


def test_g5_3_operators_do_not_see_cost_or_accuracy(
    phase5_client: Phase5Client, metrics_tenant: Tenant
) -> None:
    response = phase5_client.request(
        "GET", "/api/metrics/summary", token=metrics_tenant.operator
    )
    assert response.status == 200, detail(response)
    body = response.body
    for key in ADMIN_ONLY_KEYS:
        assert key not in body, (
            f"{key} is visible to an operator; D19 decision 6 makes spend and "
            "model accuracy administrator-only"
        )
    # Everything else stays visible: the restriction is about oversight figures,
    # not about hiding the operator's own work from them.
    for key in (
        "total_runs",
        "waiting_approvals",
        "approval_rate",
        "retrieval_success",
        "avg_tokens_per_run",
    ):
        assert key in body, key


def test_g5_3_metrics_are_tenant_scoped(
    phase5_client: Phase5Client, metrics_tenant: Tenant, phase5_database_url: str
) -> None:
    """Another organization's runs must not appear in these totals.

    The dataset above is exactly what makes this checkable: a neighbouring
    tenant with a known 5 runs would show up immediately.
    """
    neighbour = new_tenant(phase5_client, phase5_database_url)
    response = phase5_client.request(
        "GET", "/api/metrics/summary", token=neighbour.admin
    )
    assert response.status == 200, detail(response)
    assert response.body["total_runs"] == 0, response.body


def test_g5_3_audit_endpoint_is_administrator_only_and_filterable(
    phase5_client: Phase5Client, metrics_tenant: Tenant
) -> None:
    operator = phase5_client.request("GET", "/api/audit", token=metrics_tenant.operator)
    assert operator.status == 403, detail(operator)

    admin = phase5_client.request(
        "GET", "/api/audit?limit=100", token=metrics_tenant.admin
    )
    assert admin.status == 200, detail(admin)
    assert admin.body["total"] == 8, admin.body

    filtered = phase5_client.request(
        "GET", "/api/audit?tool=llm.judge", token=metrics_tenant.admin
    )
    assert filtered.status == 200, detail(filtered)
    assert filtered.body["total"] == 1, filtered.body
    assert filtered.body["entries"][0]["tokens_in"] == 30, filtered.body


def test_g5_3_agent_config_is_readable_by_any_persona(
    phase5_client: Phase5Client, metrics_tenant: Tenant
) -> None:
    for role in ("administrator", "operator", "approver"):
        response = phase5_client.request(
            "GET", "/api/config/agent", token=metrics_tenant.tokens[role]
        )
        assert response.status == 200, f"{role}: {detail(response)}"
        body = response.body
        assert body["agent_version"], body
        assert body["judge_model"] != body["triage_model"], body
        assert set(body["taxonomy"]) == {
            "categories",
            "urgencies",
            "teams",
            "priorities",
        }, body
