from __future__ import annotations

import importlib
import json
import sys
from enum import Enum
from pathlib import Path

from conftest import (
    Phase2Client,
    assert_failure_reason,
    audit_entries_from,
    evidence_from,
    fake_completion_directive,
    llm_audit_entries,
    operation_name,
    triage_and_wait,
)

TRIAGE_FIELDS = {
    "summary",
    "category",
    "urgency",
    "recommended_team",
    "suggested_priority",
    "recommended_resolution",
    "confidence",
    "requires_approval",
    "citations",
}
CITATION_FIELDS = {
    "chunk_id",
    "document_title",
    "page",
    "section",
    "claim",
}


def _runtime_module(repository_root: Path, name: str) -> object:
    backend = str(repository_root / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    return importlib.import_module(name)


def _enum_value_sets(module: object) -> set[frozenset[str]]:
    enum_sets: set[frozenset[str]] = set()
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, Enum)
            and value is not Enum
            and value.__module__ == module.__name__
        ):
            enum_sets.add(frozenset(str(member.value) for member in value))
    return enum_sets


def test_phase2_taxonomy_fixture_matches_all_runtime_enums_exactly(
    repository_root: Path,
) -> None:
    taxonomy_path = repository_root / "fixtures" / "enterprise" / "taxonomy.json"
    fixture = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    fixture_sets = {
        frozenset(fixture["categories"]),
        frozenset(fixture["urgencies"]),
        frozenset(fixture["priorities"]),
        frozenset(fixture["recommended_teams"]),
    }

    taxonomy_module = _runtime_module(repository_root, "app.agents.taxonomy")
    runtime_sets = _enum_value_sets(taxonomy_module)

    assert len(runtime_sets) == 4, (
        "backend/app/agents/taxonomy.py must define the four Phase 2 enums; "
        f"found value sets {runtime_sets!r}"
    )
    assert runtime_sets == fixture_sets, (
        "runtime taxonomy and fixtures/enterprise/taxonomy.json drifted: "
        f"runtime-only={runtime_sets - fixture_sets!r}, "
        f"fixture-only={fixture_sets - runtime_sets!r}"
    )


def test_g2_1_completed_run_has_exact_pydantic_valid_output_and_evidence(
    repository_root: Path,
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
) -> None:
    del corpus_ready
    _, run = triage_and_wait(
        phase2_client,
        org_id=corpus_org_id,
        title="MeridianConnect drops every few minutes",
        description=(
            "One remote employee loses the company VPN every five minutes, but an "
            "alternate network is a working temporary workaround."
        ),
        service="MeridianConnect VPN",
    )

    assert run["status"] == "completed", run
    assert isinstance(run.get("agent_version"), str) and run["agent_version"].strip()
    output = run.get("output")
    assert isinstance(output, dict), run
    assert set(output) == TRIAGE_FIELDS, (
        f"completed output must exactly match the MVP JSON: {output!r}"
    )

    schema_module = _runtime_module(repository_root, "app.agents.schema")
    triage_result = schema_module.TriageResult
    validated = triage_result.model_validate(output)
    assert validated.model_dump(mode="json") == output

    citations = output["citations"]
    assert isinstance(citations, list) and citations
    for citation in citations:
        assert isinstance(citation, dict)
        assert set(citation) == CITATION_FIELDS
        assert isinstance(citation["chunk_id"], str) and citation["chunk_id"].strip()
        assert (
            isinstance(citation["document_title"], str)
            and citation["document_title"].strip()
        )
        assert isinstance(citation["claim"], str) and citation["claim"].strip()

    assert evidence_from(run), "a completed run must expose the evidence it cited"
    assert audit_entries_from(run), "a completed run must expose its audit entries"


def test_g2_1_unparseable_output_retries_once_then_fails_closed(
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
) -> None:
    del corpus_ready
    directive = fake_completion_directive("unparseable")
    _, run = triage_and_wait(
        phase2_client,
        org_id=corpus_org_id,
        title="Schema fail-closed acceptance probe",
        description=(
            "A single employee needs routine VPN troubleshooting. " f"{directive}"
        ),
        service="MeridianConnect VPN",
    )

    assert run["status"] == "failed", run
    assert_failure_reason(run, "schema_invalid")
    assert run.get("output") is None or run.get("output") == {}, (
        "invalid model output must never be stored as a completed triage result"
    )
    entries = audit_entries_from(run)
    assert len(llm_audit_entries(entries)) == 2, (
        "unparseable output must cause exactly one repair retry; "
        f"audit tools={[operation_name(entry) for entry in entries]!r}"
    )
