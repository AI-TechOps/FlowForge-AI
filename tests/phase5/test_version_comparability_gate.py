"""G5.5 — two batches at different agent versions are directly comparable.

Comparability is a shape claim: every batch summary carries the same metric
keys, whatever happened during the batch. A key that appears only when a metric
happens to be measurable makes the regression table ragged exactly when
something went wrong — which is the moment you most want to read it.

Two batches at *different* agent versions are seeded here directly rather than
produced by running the agent twice, because there is no way to run the shipping
code at a previous `AGENT_VERSION`, and a comparability gate that could only
compare a version to itself would prove nothing.

The regression table in `eval/baseline.md` is checked too: the protocol says a
prompt or model change without a fresh row is a convention violation, so the
table having comparable rows is part of the gate rather than a docs nicety.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from .conftest import (
    REPOSITORY_ROOT,
    Phase5Client,
    Tenant,
    connect,
    detail,
    new_tenant,
    runtime_module,
)

scoring = runtime_module("app.eval.scoring")

BASELINE = REPOSITORY_ROOT / "eval" / "baseline.md"


def _scores(correct: bool, judged: bool) -> dict[str, Any]:
    return {
        **{
            field: {"expected": "network_access", "actual": None, "correct": correct}
            for field in scoring.SCORED_FIELDS
        },
        "grounded": correct,
        "retrieval_hit": correct,
        **({"resolution_quality": 4, "citation_support": 4} if judged else {}),
    }


async def _seed_two_versions(database_url: str, org_id: str) -> None:
    """One older batch that went well, one newer batch that scored nothing.

    The second is the interesting case: a batch where every run failed and no
    judgement was possible still has to present the full metric set, or the two
    rows cannot be read side by side.
    """
    org = UUID(org_id)
    now = datetime.now(UTC)
    old_summary = scoring.summarize(
        [
            {"scores": _scores(correct=True, judged=True), "failure_reason": None},
            {"scores": _scores(correct=False, judged=True), "failure_reason": None},
        ]
    )
    new_summary = scoring.summarize(
        [
            {
                "scores": _scores(correct=False, judged=False),
                "failure_reason": "ungrounded",
            }
        ]
    )

    connection = await connect(database_url)
    try:
        for agent_version, summary, created in (
            ("triage-v0", old_summary, now - timedelta(days=2)),
            ("triage-v1", new_summary, now),
        ):
            await connection.execute(
                """
                INSERT INTO eval_batches (
                    id, org_id, agent_version, llm_provider, triage_model, judge_model,
                    status, total_tickets, started_at, finished_at, summary, created_at
                )
                VALUES ($1, $2, $3, 'ollama', 'llama3.1:8b', 'qwen2.5:7b',
                        'completed'::eval_batch_status, 20, $4, $4, $5::jsonb, $4)
                """,
                uuid4(),
                org,
                agent_version,
                created,
                json.dumps(summary),
            )
    finally:
        await connection.close()


def test_g5_5_summary_keys_do_not_depend_on_what_was_measured() -> None:
    """The offline half: shape is fixed even for a batch that scored nothing."""
    rich = scoring.summarize(
        [
            {"scores": _scores(correct=True, judged=True), "failure_reason": None},
            {"scores": _scores(correct=False, judged=True), "failure_reason": None},
        ]
    )
    barren = scoring.summarize(
        [
            {
                "scores": _scores(correct=False, judged=False),
                "failure_reason": "ungrounded",
            }
        ]
    )
    empty = scoring.summarize([])
    assert set(rich) == set(barren) == set(empty), {
        "rich_only": sorted(set(rich) - set(barren)),
        "barren_only": sorted(set(barren) - set(rich)),
        "empty_only": sorted(set(empty) - set(rich)),
    }
    # And the keys the regression table is written against.
    assert {
        "accuracy_overall",
        "accuracy_category",
        "grounded_rate",
        "retrieval_hit_at_k",
        "judge_resolution_quality_mean",
        "total_tickets",
        "failed_runs",
    } <= set(rich), sorted(rich)


@pytest.fixture(scope="module")
def versions_tenant(phase5_client: Phase5Client, phase5_database_url: str) -> Tenant:
    tenant = new_tenant(phase5_client, phase5_database_url)
    asyncio.run(_seed_two_versions(phase5_database_url, tenant.org_id))
    return tenant


def test_g5_5_two_versions_appear_side_by_side_with_identical_metric_keys(
    phase5_client: Phase5Client, versions_tenant: Tenant
) -> None:
    response = phase5_client.request(
        "GET", "/api/eval/batches", token=versions_tenant.admin
    )
    assert response.status == 200, detail(response)
    batches = response.body
    assert len(batches) == 2, batches

    # Newest first: the regression table reads top-down.
    assert [batch["agent_version"] for batch in batches] == [
        "triage-v1",
        "triage-v0",
    ], batches
    key_sets = [frozenset(batch["summary"]) for batch in batches]
    assert key_sets[0] == key_sets[1], {
        "newer_only": sorted(key_sets[0] - key_sets[1]),
        "older_only": sorted(key_sets[1] - key_sets[0]),
    }
    for batch in batches:
        # Each row must carry what it was produced by, or "did that change
        # help?" has no answer.
        assert (
            batch["agent_version"] and batch["triage_model"] and batch["judge_model"]
        ), batch
        # And which provider produced it: the fake provider runs under the
        # configured model name, so a harness row and a real row are otherwise
        # indistinguishable -- two rows that look comparable but are not.
        assert batch["llm_provider"], batch


def test_g5_5_batches_are_tenant_scoped(
    phase5_client: Phase5Client, versions_tenant: Tenant, phase5_database_url: str
) -> None:
    neighbour = new_tenant(phase5_client, phase5_database_url)
    response = phase5_client.request("GET", "/api/eval/batches", token=neighbour.admin)
    assert response.status == 200, detail(response)
    assert response.body == [], response.body


def test_g5_5_a_foreign_batch_is_not_readable(
    phase5_client: Phase5Client, versions_tenant: Tenant, phase5_database_url: str
) -> None:
    listing = phase5_client.request(
        "GET", "/api/eval/batches", token=versions_tenant.admin
    )
    batch_id = listing.body[0]["id"]
    neighbour = new_tenant(phase5_client, phase5_database_url)
    response = phase5_client.request(
        "GET", f"/api/eval/batches/{batch_id}", token=neighbour.admin
    )
    # 404, not 403: never confirm another tenant's rows exist.
    assert response.status == 404, detail(response)


def _baseline_table() -> list[list[str]]:
    """The Phase 5 regression table, as rows of cells."""
    text = BASELINE.read_text(encoding="utf-8")
    section = text.split("## Phase 5 eval batches", 1)
    assert len(section) == 2, (
        "eval/baseline.md has no '## Phase 5 eval batches' section; the "
        "regression protocol needs one table with comparable rows"
    )
    rows = []
    for line in section[1].splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def test_g5_5_baseline_table_has_at_least_two_comparable_entries() -> None:
    """The definition of done: >=2 entries demonstrating regression tracking.

    Read as a table rather than eyeballed, because "comparable" means the rows
    have the same columns — a row with a metric the previous row lacks is
    exactly the ragged table this gate exists to prevent.
    """
    rows = _baseline_table()
    assert len(rows) >= 3, f"expected a header and >=2 data rows, got {rows}"
    header, *data = rows
    assert len(data) >= 2, f"regression table has {len(data)} entry/entries: {data}"
    for row in data:
        assert len(row) == len(header), (
            f"row {row} has {len(row)} cells against a {len(header)}-column header; "
            "two versions can only be compared if their metrics line up"
        )
    for column in ("agent_version", "overall"):
        assert any(
            column in cell.lower() for cell in header
        ), f"the regression table has no {column} column: {header}"


def test_g5_5_baseline_names_the_models_each_row_was_produced_by() -> None:
    header, *data = _baseline_table()
    assert any("model" in cell.lower() for cell in header), header
    for row in data:
        assert any(row), row
