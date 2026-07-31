from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Phase2Client, triage_and_wait


def _require_real_triage_model() -> None:
    """G2.4 is the one gate that measures answer quality, not plumbing.

    The fake provider classifies by hashing token content (D16 decision 3), so
    its accuracy is noise by construction — scoring it would produce a number
    that means nothing and a red gate that signals nothing. The rest of the
    Phase 2 gates run on it precisely because they test plumbing.
    """
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider not in {"ollama", "openai"}:
        pytest.skip(
            "G2.4 needs a real triage model; the stack under test reports "
            f"LLM_PROVIDER={provider or '(unset)'}. Run against an Ollama- or "
            "OpenAI-backed stack with LLM_PROVIDER set to match, then record the "
            "number in eval/baseline.md."
        )


def test_g2_4_seed_set_category_accuracy_is_at_least_seventy_percent(
    repository_root: Path,
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
    record_property: Callable[[str, object], None],
) -> None:
    del corpus_ready
    _require_real_triage_model()
    fixture_path = repository_root / "fixtures" / "eval_tickets.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    tickets = payload.get("eval_tickets")
    assert isinstance(tickets, list) and tickets, (
        "G2.4 requires a non-empty fixtures/eval_tickets.json seed set"
    )
    backend = str(repository_root / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    triage_result = importlib.import_module("app.agents.schema").TriageResult

    correct = 0
    observations: list[str] = []
    for raw_ticket in tickets:
        assert isinstance(raw_ticket, dict)
        labels = raw_ticket.get("labels")
        assert isinstance(labels, dict)
        expected = labels.get("category")
        assert isinstance(expected, str) and expected

        _, run = triage_and_wait(
            phase2_client,
            org_id=corpus_org_id,
            title=str(raw_ticket["title"]),
            description=str(raw_ticket["description"]),
            department=str(raw_ticket["requester_department"]),
            service=str(raw_ticket["affected_service"]),
            priority=str(raw_ticket.get("existing_priority") or "P3"),
        )
        output = run.get("output")
        predicted = output.get("category") if isinstance(output, dict) else None
        if run.get("status") == "completed":
            assert isinstance(output, dict), (
                f"completed seed run has no structured output: {run!r}"
            )
            triage_result.model_validate(output)
            if predicted == expected:
                correct += 1
        observations.append(
            f"{raw_ticket.get('id')}: expected={expected}, "
            f"predicted={predicted}, status={run.get('status')}"
        )

    accuracy = correct / len(tickets)
    record_property("phase2_eval_correct", correct)
    record_property("phase2_eval_total", len(tickets))
    record_property("phase2_category_accuracy", accuracy)
    assert accuracy >= 0.70, (
        f"G2.4 category accuracy was {correct}/{len(tickets)} ({accuracy:.1%}); "
        "required >=70%.\n" + "\n".join(observations)
    )
