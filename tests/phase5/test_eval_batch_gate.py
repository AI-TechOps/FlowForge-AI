"""G5.4 — an eval batch covers every seed ticket and always completes.

Two halves, and the structural one is the load-bearing half:

* **Structure (offline):** `build_graph(eval_mode=True)` must not *contain* the
  approval or execute nodes. Removing them rather than skipping them at runtime
  is D19 decision 2 — a flag that can be set can be set wrongly on a real run,
  and the thing it would switch off is the human-in-the-loop this whole project
  is built around.
* **Behaviour (live):** a batch triages every `is_eval_seed` ticket, finishes
  even when individual runs fail, and never strands a run at
  `awaiting_approval`. And a *normal* run still pauses — which is what makes
  "eval mode cannot pause" a statement about eval mode rather than a regression
  in the approval flow.

The live half also carries G5.1's recorded-batch claim: the stored per-ticket
scores must re-score to the summary the batch stored.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from .conftest import (
    Phase5Client,
    Tenant,
    detail,
    new_tenant,
    runtime_module,
    seed_eval_tickets,
    wait_for_batch,
    wait_for_document,
)

scoring = runtime_module("app.eval.scoring")

# Enough tickets to be a real batch, few enough to finish inside a CI job. The
# gate is "100% of the seed tickets in this organization", so coverage is
# asserted against what was seeded, not against the fixture's full 20.
TICKET_COUNT = int(os.environ.get("PHASE5_EVAL_TICKETS", "3"))

POLICY = """# MeridianConnect VPN access policy

## Section 5 - repeated disconnections

Repeated MeridianConnect disconnections are owned by IT Infrastructure. Confirm
the client is on the current build, disable split tunnelling, and reconnect over
a wired network before escalating. Treat a full outage as high urgency and a
single user's intermittent drops as medium.

## Section 6 - access requests

New VPN access requests are routed to IT Infrastructure once the requester's
manager has approved them. Hardware faults go to Workplace Technology.
"""


def _graph_nodes(eval_mode: bool) -> set[str]:
    graph_module = runtime_module("app.agents.graph")
    compiled = graph_module.build_graph(eval_mode=eval_mode)
    return set(compiled.get_graph().nodes)


def test_g5_4_eval_mode_graph_has_no_approval_or_execute_node() -> None:
    nodes = _graph_nodes(eval_mode=True)
    assert "propose" in nodes, nodes
    assert "await_approval" not in nodes, (
        "the eval graph still contains the approval node; a batch could pause "
        "and D19 decision 2 asks for the node to be absent, not skipped"
    )
    assert "execute" not in nodes, (
        "the eval graph can reach a write node; an eval run must be unable to "
        "write, not merely unlikely to"
    )


def test_g5_4_the_normal_graph_still_contains_both() -> None:
    """The other side of the same coin.

    If eval mode were implemented by deleting the nodes outright, this test is
    the one that fails.
    """
    nodes = _graph_nodes(eval_mode=False)
    assert {"await_approval", "execute"} <= nodes, nodes


def test_g5_4_only_the_eval_batch_endpoint_marks_a_run_as_eval() -> None:
    """`eval_batch_id` is the single marker, and one module sets it.

    A second place that could set it would be a second place that could stop a
    run from pausing for approval.
    """
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[2] / "backend" / "app"
    setters = [
        path.relative_to(backend).as_posix()
        for path in backend.rglob("*.py")
        if "eval_batch_id=" in path.read_text(encoding="utf-8")
    ]
    assert setters == ["api/evaluation.py"], (
        f"eval_batch_id is assigned in {setters}; it must be set only where a "
        "batch is created"
    )


@pytest.fixture(scope="module")
def batch_tenant(phase5_client: Phase5Client, phase5_database_url: str) -> Tenant:
    tenant = new_tenant(phase5_client, phase5_database_url)
    upload = phase5_client.upload_markdown(
        tenant.admin, title="Phase 5 MeridianConnect VPN policy", body=POLICY
    )
    assert upload.status in {200, 201, 202}, detail(upload)
    wait_for_document(phase5_client, tenant.admin, upload.body["id"])
    seed_eval_tickets(phase5_database_url, tenant.org_id, TICKET_COUNT)
    return tenant


@pytest.fixture(scope="module")
def batch(phase5_client: Phase5Client, batch_tenant: Tenant) -> dict[str, Any]:
    started = phase5_client.request("POST", "/api/eval/run", token=batch_tenant.admin)
    assert started.status == 202, detail(started)
    assert started.body["total_tickets"] == TICKET_COUNT, started.body
    return wait_for_batch(phase5_client, batch_tenant.admin, started.body["id"])


def test_g5_4_a_batch_is_administrator_only(
    phase5_client: Phase5Client, batch_tenant: Tenant
) -> None:
    for role in ("operator", "approver"):
        response = phase5_client.request(
            "POST", "/api/eval/run", token=batch_tenant.tokens[role]
        )
        assert response.status == 403, f"{role}: {detail(response)}"


def test_g5_4_batch_covers_every_seed_ticket(batch: dict[str, Any]) -> None:
    assert batch["status"] == "completed", batch
    assert (
        len(batch["results"]) == TICKET_COUNT
    ), f"batch scored {len(batch['results'])} of {TICKET_COUNT} seed tickets"
    assert batch["summary"]["total_tickets"] == TICKET_COUNT, batch["summary"]
    seed_refs = {result["seed_ref"] for result in batch["results"]}
    assert len(seed_refs) == TICKET_COUNT, seed_refs


def test_g5_4_failures_are_counted_not_crashed_on(batch: dict[str, Any]) -> None:
    """A failed run is a scored ticket, not a lost one.

    scored + failed must account for every ticket; anything else means the
    batch quietly dropped a run, and a batch that drops its failures reports
    the happy path as accuracy.
    """
    summary = batch["summary"]
    assert (
        summary["scored_tickets"] + summary["failed_runs"] == summary["total_tickets"]
    ), summary
    for result in batch["results"]:
        if result["failure_reason"]:
            scores = result["scores"]
            assert all(
                scores[field]["correct"] is False for field in scoring.SCORED_FIELDS
            ), f"a failed run scored as correct: {result}"


def test_g5_4_no_eval_run_ever_waits_for_approval(
    phase5_client: Phase5Client, batch_tenant: Tenant, batch: dict[str, Any]
) -> None:
    response = phase5_client.request(
        "GET", "/api/runs?include_eval=true&limit=500", token=batch_tenant.admin
    )
    assert response.status == 200, detail(response)
    eval_runs = [
        run for run in response.body["runs"] if run["eval_batch_id"] == batch["id"]
    ]
    assert len(eval_runs) == TICKET_COUNT, eval_runs
    stranded = [run for run in eval_runs if run["status"] == "awaiting_approval"]
    assert not stranded, (
        f"{len(stranded)} eval runs are waiting for a human who has nothing to "
        f"decide: {stranded}"
    )


def test_g5_4_eval_runs_are_hidden_from_the_default_run_history(
    phase5_client: Phase5Client, batch_tenant: Tenant, batch: dict[str, Any]
) -> None:
    response = phase5_client.request("GET", "/api/runs", token=batch_tenant.admin)
    assert response.status == 200, detail(response)
    assert all(
        run["eval_batch_id"] is None for run in response.body["runs"]
    ), response.body


def test_g5_4_a_normal_run_still_pauses(
    phase5_client: Phase5Client, batch_tenant: Tenant
) -> None:
    """Eval mode must not have cost the human-in-the-loop anything."""
    ticket = phase5_client.request(
        "POST",
        "/api/tickets",
        token=batch_tenant.operator,
        json_body={
            "title": "MeridianConnect drops every few minutes",
            "description": (
                "From home, MeridianConnect disconnects about every five minutes. "
                "Ordinary websites still work."
            ),
            "department": "Customer Success",
            "service": "MeridianConnect VPN",
            "priority": "P3",
        },
    )
    assert ticket.status in {200, 201}, detail(ticket)
    started = phase5_client.request(
        "POST",
        "/api/runs",
        token=batch_tenant.operator,
        json_body={"ticket_id": ticket.body["id"]},
    )
    assert started.status == 202, detail(started)

    run_id = started.body["id"]
    deadline = time.monotonic() + float(
        os.environ.get("PHASE5_RUN_TIMEOUT_SECONDS", "180")
    )
    last: Any = None
    while time.monotonic() < deadline:
        response = phase5_client.request(
            "GET", f"/api/runs/{run_id}", token=batch_tenant.operator
        )
        assert response.status == 200, detail(response)
        last = response.body
        if last["status"] == "awaiting_approval":
            assert last["eval_batch_id"] is None, last
            return
        assert last["status"] not in {
            "completed",
            "rejected",
        }, f"a normal run reached {last['status']} without pausing for approval: {last}"
        if last["status"] == "failed":
            pytest.skip(
                f"normal run failed before the pause ({last['failure_reason']}); "
                "that is a Phase 2/3 concern, not an eval-mode one"
            )
        time.sleep(1)
    pytest.fail(f"normal run never reached awaiting_approval: {last!r}")


def test_g5_1_recorded_batch_rescores_to_its_stored_summary(
    batch: dict[str, Any],
) -> None:
    """G5.1's live half, asserted on the batch this module recorded.

    Recomputing the summary from the stored per-ticket scores is exactly what a
    re-score does. Disagreement here means the regression table is comparing
    numbers from two different scorers.
    """
    recomputed = scoring.summarize(
        [
            {"scores": result["scores"], "failure_reason": result["failure_reason"]}
            for result in batch["results"]
        ]
    )
    assert recomputed == batch["summary"], f"{recomputed} != {batch['summary']}"
