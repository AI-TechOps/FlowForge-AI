from __future__ import annotations

import json

import pytest

from tests.phase2.conftest import (
    Phase2Client,
    audit_entries_from,
    evidence_from,
    fake_completion_directive,
    response_detail,
    run_id_from,
    ticket_id_from,
    triage_and_wait,
    wait_for_run,
)


def test_phase2_audit_never_repeats_a_credential_from_ticket_text(
    phase2_client: Phase2Client,
    empty_org_id: str,
) -> None:
    secret_marker = "ff_adversarial_secret_7b31f0d5"
    _, run = triage_and_wait(
        phase2_client,
        org_id=empty_org_id,
        title="Credential redaction probe",
        description=(
            "A user pasted a connection string while asking for help: "
            f"postgresql://flowforge:{secret_marker}@db.internal/support and "
            f"Authorization: Bearer {secret_marker}."
        ),
    )

    assert run["status"] == "failed", run
    serialized_audit = json.dumps(audit_entries_from(run)).lower()
    assert secret_marker not in serialized_audit, (
        "audit payloads/results must redact credential values even when a user "
        "placed them inside ticket text"
    )
    assert "postgresql://" not in serialized_audit
    assert "bearer " not in serialized_audit


def test_phase2_ungrounded_failure_keeps_its_retrieved_evidence_after_rollback(
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
) -> None:
    del corpus_ready
    _, run = triage_and_wait(
        phase2_client,
        org_id=corpus_org_id,
        title="Grounding rollback evidence probe",
        description=(
            "A remote employee needs the documented VPN recovery steps. "
            f"{fake_completion_directive('no_citations')}"
        ),
        service="MeridianConnect VPN",
    )

    assert run["status"] == "failed", run
    assert run.get("failure_reason") == "ungrounded", run
    assert evidence_from(run), (
        "rollback must not erase evidence retrieved before grounding failed"
    )
    assert "audit_entries" in run, (
        "the run-detail contract names the trail audit_entries"
    )
    assert audit_entries_from(run), (
        "the failed run must retain its tool and LLM audit trail"
    )


def test_phase2_run_detail_is_invisible_to_a_different_organization(
    phase2_client: Phase2Client,
    isolation_org_ids: tuple[str, str],
) -> None:
    org_a_id, org_b_id = isolation_org_ids
    ticket = phase2_client.create_ticket(
        org_b_id,
        title="Organization B run-detail probe",
        description="Only organization B may inspect this run, its evidence, or its audit trail.",
    )
    ticket_id = ticket_id_from(ticket)
    run_id = run_id_from(phase2_client.triage(org_b_id, ticket_id))

    cross_org = phase2_client.get_run(org_a_id, run_id)
    assert cross_org.status in {403, 404}, response_detail(cross_org)

    owner_run = wait_for_run(phase2_client, org_id=org_b_id, run_id=run_id)
    assert owner_run["status"] in {"completed", "failed"}, owner_run
    cross_org_after_terminal = phase2_client.get_run(org_a_id, run_id)
    assert cross_org_after_terminal.status in {403, 404}, response_detail(
        cross_org_after_terminal
    )


def test_fake_completion_directive_is_refused_with_fake_provider_in_prod() -> None:
    pytest.importorskip("pydantic_settings")
    from app.config import Settings
    from app.llm.provider import get_provider

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        redis_url="redis://127.0.0.1:1/0",
        llm_provider="fake",
        app_env="prod",
    )
    with pytest.raises(ValueError, match="dev/CI only"):
        get_provider(settings)


def test_fake_completion_directive_has_no_interpreter_on_real_provider_adapters() -> (
    None
):
    pytest.importorskip("pydantic_settings")
    from app.llm.provider import FakeProvider, OllamaProvider, OpenAIProvider

    directive = fake_completion_directive("unparseable")
    fake = FakeProvider("embedding")
    assert fake._injected_mode(directive) == ("unparseable", None)

    ollama = OllamaProvider("http://127.0.0.1:1", "embedding", "triage")
    openai = OpenAIProvider("placeholder", "embedding", "triage")
    assert not hasattr(ollama, "_injected_mode")
    assert not hasattr(openai, "_injected_mode")
