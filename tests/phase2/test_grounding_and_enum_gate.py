from __future__ import annotations

import pytest

from .conftest import (
    Phase2Client,
    assert_failure_reason,
    audit_entries_from,
    fake_completion_directive,
    llm_audit_entries,
    operation_name,
    triage_and_wait,
)


def test_g2_2_empty_knowledge_base_fails_as_ungrounded(
    phase2_client: Phase2Client,
    empty_org_id: str,
) -> None:
    _, run = triage_and_wait(
        phase2_client,
        org_id=empty_org_id,
        title="No-knowledge grounding acceptance probe",
        description="A single user reports that the company VPN will not connect.",
        service="MeridianConnect VPN",
    )

    assert run["status"] == "failed", run
    assert_failure_reason(run, "ungrounded")
    assert run.get("output") is None or run.get("output") == {}, (
        "a zero-valid-citation result must never be exposed as completed output"
    )


@pytest.mark.parametrize(
    "field",
    ["category", "urgency", "suggested_priority", "recommended_team"],
)
def test_g2_3_out_of_taxonomy_value_retries_once_then_fails(
    field: str,
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
) -> None:
    del corpus_ready
    directive = fake_completion_directive("bad_enum", field=field)
    _, run = triage_and_wait(
        phase2_client,
        org_id=corpus_org_id,
        title=f"Invalid {field} acceptance probe",
        description=(
            "A single employee needs routine password-lockout assistance. "
            f"{directive}"
        ),
        service="Meridian identity",
    )

    assert run["status"] == "failed", run
    assert_failure_reason(run, "schema_invalid")
    entries = audit_entries_from(run)
    llm_entries = llm_audit_entries(entries)
    assert len(llm_entries) == 2, (
        f"invalid {field} must receive one repair retry; "
        f"audit tools={[operation_name(entry) for entry in entries]!r}"
    )
