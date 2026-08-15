from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import TRIAGE_SUCCESS_STATUSES, Phase2Client, triage_and_wait


def _require_armed_gate() -> None:
    """G2.4 is the one gate that measures answer quality, not plumbing.

    The fake provider classifies by hashing token content (D16 decision 3), so
    its accuracy is noise by construction — scoring it would produce a number
    that means nothing and a red gate that signals nothing. The rest of the
    Phase 2 gates run on it precisely because they test plumbing.

    Arming is explicit rather than inferred. An earlier version read
    LLM_PROVIDER from the pytest process, which says nothing about the provider
    the running stack uses — the documented workflow passes .env to Docker
    Compose only, so the variable is typically unset here while the backend is
    perfectly real (Codex Phase 2 escalation).
    """
    if os.environ.get("PHASE2_RUN_EVAL", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        pytest.skip(
            "G2.4 measures real-model accuracy and is opt-in: set PHASE2_RUN_EVAL=1 "
            "against an Ollama- or OpenAI-backed stack, then record the number in "
            "eval/baseline.md."
        )


def _assert_stack_is_not_fake(run: dict[str, object]) -> None:
    """Verify the provider from the stack's own audit trail, not from env.

    Every classify call records the model it used, so the run just executed is
    direct evidence of what answered. An armed gate pointed at a fake backend
    must fail loudly, never quietly score noise.
    """
    entries = run.get("audit_entries")
    assert isinstance(entries, list), f"run detail lacks audit_entries: {run!r}"
    models = {
        str(result.get("model"))
        for entry in entries
        if isinstance(entry, dict) and isinstance(result := entry.get("result"), dict)
        if result.get("model")
    }
    assert models, f"no LLM audit row recorded a model name: {run!r}"
    fake_models = {model for model in models if model.startswith("fake:")}
    assert not fake_models, (
        f"G2.4 is armed but the stack answered with {sorted(fake_models)}. "
        "The fake provider's accuracy is noise by construction (D16 decision 3) — "
        "point PHASE2_RUN_EVAL at an Ollama- or OpenAI-backed stack."
    )


def test_g2_4_seed_set_category_accuracy_is_at_least_seventy_percent(
    repository_root: Path,
    phase2_client: Phase2Client,
    corpus_org_id: str,
    corpus_ready: None,
    record_property: Callable[[str, object], None],
) -> None:
    del corpus_ready
    _require_armed_gate()
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
    checked_provider = False
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
        if not checked_provider:
            _assert_stack_is_not_fake(run)
            checked_provider = True

        output = run.get("output")
        predicted = output.get("category") if isinstance(output, dict) else None
        # From Phase 3 a successful triage rests at `awaiting_approval` with its
        # output final; scoring only `completed` would report 0% accuracy for a
        # perfectly good agent. (Phase 5's eval mode runs the graph to `propose`
        # without an interrupt — spec 06 §2 — which removes the ambiguity.)
        if run.get("status") in TRIAGE_SUCCESS_STATUSES:
            assert isinstance(output, dict), (
                f"settled seed run has no structured output: {run!r}"
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
