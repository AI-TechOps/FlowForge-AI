from __future__ import annotations

import json
import os
from typing import Any

import pytest
from conftest import (
    READ_TOOL_NAMES,
    Phase2Client,
    audit_entries_from,
    llm_audit_entries,
    operation_name,
    run_detail_from,
    triage_and_wait,
)

AUDIT_FIELDS = {
    "actor",
    "tool",
    "payload",
    "result",
    "latency_ms",
    "tokens_in",
    "tokens_out",
    "cost_estimate",
}
FORBIDDEN_PAYLOAD_KEYS = {
    "api_key",
    "authorization",
    "access_token",
    "refresh_token",
    "connection_string",
    "database_url",
    "password",
    "secret",
}


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key).lower() for key in value]
        for nested in value.values():
            keys.extend(_walk_keys(nested))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for nested in value:
            keys.extend(_walk_keys(nested))
        return keys
    return []


def _assert_audit_shape(entry: dict[str, object]) -> None:
    missing = AUDIT_FIELDS - entry.keys()
    assert not missing, f"audit row is missing fields {sorted(missing)}: {entry!r}"
    assert isinstance(entry["actor"], str) and entry["actor"]
    assert isinstance(entry["payload"], dict)
    assert isinstance(entry["latency_ms"], int | float) and entry["latency_ms"] >= 0
    for field in ("tokens_in", "tokens_out", "cost_estimate"):
        value = entry[field]
        assert value is None or isinstance(value, int | float), (
            f"audit {field} must be recorded as a number or explicit null: {entry!r}"
        )
        if isinstance(value, int | float):
            assert value >= 0

    payload_keys = set(_walk_keys(entry["payload"]))
    assert payload_keys.isdisjoint(FORBIDDEN_PAYLOAD_KEYS), (
        "audit payload contains a credential-bearing key: "
        f"{sorted(payload_keys & FORBIDDEN_PAYLOAD_KEYS)}"
    )
    serialized = json.dumps(entry["payload"]).lower()
    assert "postgresql://" not in serialized and "postgres://" not in serialized
    assert "bearer " not in serialized


def test_g2_5_graph_call_trace_exactly_matches_complete_audit_rows(
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
) -> None:
    del corpus_ready
    _, run = triage_and_wait(
        phase2_client,
        org_id=corpus_org_id,
        title="Audit completeness acceptance probe",
        description=(
            "One employee is locked out after five incorrect password attempts and "
            "needs the documented recovery procedure."
        ),
        service="Meridian identity",
    )
    assert run["status"] == "completed", run

    entries = audit_entries_from(run)
    names = [operation_name(entry) for entry in entries]
    # The approved deterministic graph has exactly two direct read-tool calls and
    # one structured LLM call on the successful, no-retry path.
    assert len(entries) == 3, (
        "successful graph trace is get_ticket + search_company_knowledge + one LLM "
        f"call, but audit rows were {names!r}"
    )
    for expected_tool in READ_TOOL_NAMES:
        assert names.count(expected_tool) == 1, (
            f"graph trace contains one {expected_tool} call; audit rows were {names!r}"
        )
    assert len(llm_audit_entries(entries)) == 1, (
        f"successful graph trace contains one LLM call; audit rows were {names!r}"
    )
    for entry in entries:
        _assert_audit_shape(entry)


def test_g2_5_human_end_to_end_audit_spot_check_can_be_confirmed(
    phase2_client: Phase2Client,
    corpus_org_id: str,
) -> None:
    run_id = os.environ.get("PHASE2_HUMAN_AUDIT_RUN_ID")
    confirmation = os.environ.get("PHASE2_HUMAN_AUDIT_CONFIRMED")
    if not run_id and not confirmation:
        pytest.skip(
            "G2.5 also requires one human spot-check: inspect a run end-to-end, then "
            "set PHASE2_HUMAN_AUDIT_RUN_ID and PHASE2_HUMAN_AUDIT_CONFIRMED=yes"
        )
    assert run_id and confirmation, (
        "set both PHASE2_HUMAN_AUDIT_RUN_ID and PHASE2_HUMAN_AUDIT_CONFIRMED"
    )
    assert confirmation.strip().lower() == "yes", (
        "PHASE2_HUMAN_AUDIT_CONFIRMED must be 'yes' after manual inspection"
    )

    run = run_detail_from(phase2_client.get_run(corpus_org_id, run_id))
    assert run.get("status") in {"completed", "failed"}, run
    assert audit_entries_from(run), f"confirmed run {run_id} has no audit trail"
