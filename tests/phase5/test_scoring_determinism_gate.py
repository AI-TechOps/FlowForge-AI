"""G5.1 — deterministic scores are reproducible.

The claim under test: re-scoring the same batch produces identical per-field
accuracy. That is only meaningful if the scorer is a pure function of (label,
output, evidence), so most of this file asserts the property where it lives —
in `app/eval/scoring.py` — and the live half then proves the *recorded* batch
obeys it: recomputing the summary from the stored per-ticket scores must
reproduce the summary the batch stored when it finalized.

If those two ever disagree, the regression table is comparing numbers produced
by two different scorers, which is precisely the failure G5.1 exists to catch.
"""

from __future__ import annotations

import pytest

from .conftest import runtime_module

scoring = runtime_module("app.eval.scoring")

LABEL = {
    "category": "network_access",
    "urgency": "medium",
    "recommended_team": "IT Infrastructure",
}
EVIDENCE = [
    {
        "chunk_id": "chunk-1",
        "document_title": "MD IT 001 vpn access policy",
        "text": "...",
    },
    {"chunk_id": "chunk-2", "document_title": "MD IT 004 device policy", "text": "..."},
]
OUTPUT = {
    "category": "network_access",
    "urgency": "medium",
    "recommended_team": "IT Infrastructure",
    "recommended_resolution": "Reconnect through the documented split-tunnel steps.",
    "citations": [{"chunk_id": "chunk-1", "claim": "split tunnel"}],
}


def _results() -> list[dict]:
    """A mixed batch: one perfect, one partly wrong, one failed run."""
    perfect = {
        "scores": {
            **{
                field: {
                    "expected": LABEL[field],
                    "actual": OUTPUT[field],
                    "correct": True,
                }
                for field in scoring.SCORED_FIELDS
            },
            "grounded": True,
            "retrieval_hit": True,
            "resolution_quality": 4,
            "citation_support": 5,
        },
        "failure_reason": None,
    }
    partial = {
        "scores": {
            "category": {
                "expected": "network_access",
                "actual": "hardware",
                "correct": False,
            },
            "urgency": {"expected": "medium", "actual": "medium", "correct": True},
            "recommended_team": {
                "expected": "IT Infrastructure",
                "actual": "IT Infrastructure",
                "correct": True,
            },
            "grounded": True,
            "retrieval_hit": False,
            "resolution_quality": 2,
            "citation_support": 3,
        },
        "failure_reason": None,
    }
    failed = {
        "scores": {
            **{
                field: {"expected": LABEL[field], "actual": None, "correct": False}
                for field in scoring.SCORED_FIELDS
            },
            "grounded": False,
            "retrieval_hit": None,
        },
        "failure_reason": "ungrounded",
    }
    return [perfect, partial, failed]


def test_g5_1_field_scoring_is_a_pure_function() -> None:
    first = scoring.score_fields(LABEL, OUTPUT)
    second = scoring.score_fields(dict(reversed(list(LABEL.items()))), dict(OUTPUT))
    assert first == second, "field scoring depends on dictionary ordering"
    assert all(score.correct for score in first.values()), first


def test_g5_1_summary_is_identical_across_repeated_scoring() -> None:
    results = _results()
    runs = [scoring.summarize(_results()) for _ in range(5)]
    assert all(run == runs[0] for run in runs), runs
    assert scoring.summarize(results) == runs[0]


def test_g5_1_hand_computed_summary_values() -> None:
    """Determinism is worthless if the fixed number is the wrong number."""
    summary = scoring.summarize(_results())
    assert summary["total_tickets"] == 3
    assert summary["scored_tickets"] == 2
    assert summary["failed_runs"] == 1
    # Two of three correct on urgency and team, one of three on category.
    assert summary["accuracy_category"] == pytest.approx(1 / 3, abs=1e-4)
    assert summary["accuracy_urgency"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["accuracy_recommended_team"] == pytest.approx(2 / 3, abs=1e-4)
    # All three fields right on exactly one ticket.
    assert summary["accuracy_overall"] == pytest.approx(1 / 3, abs=1e-4)
    assert summary["grounded_rate"] == pytest.approx(2 / 3, abs=1e-4)
    # hit@k skips the unmeasurable ticket: 1 of 2, not 1 of 3.
    assert summary["retrieval_hit_at_k"] == pytest.approx(0.5, abs=1e-4)
    assert summary["judge_resolution_quality_mean"] == pytest.approx(3.0, abs=1e-4)
    assert summary["judge_citation_support_mean"] == pytest.approx(4.0, abs=1e-4)
    assert summary["judged_tickets"] == 2


def test_g5_1_failed_runs_count_against_accuracy() -> None:
    """A crashing agent must not look accurate.

    The single most misleading thing an eval can do is drop the tickets it
    could not answer, so the denominator is every ticket attempted.
    """
    failed_only = [_results()[2]]
    summary = scoring.summarize(failed_only)
    assert summary["accuracy_overall"] == 0.0
    assert summary["total_tickets"] == 1
    assert summary["failed_runs"] == 1


def test_g5_1_empty_denominators_are_none_not_zero() -> None:
    summary = scoring.summarize([])
    assert summary["total_tickets"] == 0
    for key in ("accuracy_overall", "grounded_rate", "retrieval_hit_at_k"):
        assert summary[key] is None, f"{key} reports 0.0 for 'nothing measured'"


def test_g5_1_grounding_requires_a_retrieved_chunk() -> None:
    assert scoring.is_grounded(OUTPUT, EVIDENCE) is True
    # A citation naming a chunk this run never retrieved is not grounding.
    invented = {**OUTPUT, "citations": [{"chunk_id": "chunk-999"}]}
    assert scoring.is_grounded(invented, EVIDENCE) is False
    assert scoring.is_grounded(OUTPUT, []) is False
    assert scoring.is_grounded(None, EVIDENCE) is False


def test_g5_1_retrieval_hit_is_none_when_the_answer_key_is_silent() -> None:
    assert scoring.retrieval_hit([{"doc_id": "MD-IT-001"}], EVIDENCE) is True
    assert scoring.retrieval_hit([{"doc_id": "MD-HR-009"}], EVIDENCE) is False
    assert scoring.retrieval_hit([], EVIDENCE) is None
    assert scoring.retrieval_hit(None, EVIDENCE) is None


def test_g5_1_scoring_module_does_no_io() -> None:
    """Reproducibility is a property of the module, not just of these cases.

    A scorer that read a clock, a database or a model could pass every fixture
    above and still return different numbers tomorrow, so the import graph is
    asserted directly: nothing in `scoring.py` may reach a source of change.
    """
    forbidden = {"datetime", "time", "random", "app.db", "app.llm", "app.eval.judge"}
    imported = set(vars(scoring)) | {
        getattr(value, "__module__", "") for value in vars(scoring).values()
    }
    leaked = {name for name in forbidden if any(name == entry for entry in imported)}
    assert not leaked, (
        f"the deterministic scorer imports a source of variance: {leaked}"
    )


# The live half of G5.1 — that a *recorded* batch re-scores to the summary it
# stored — lives in test_eval_batch_gate.py, where a real batch exists to
# re-score. Asserting it here would mean running a second batch to check a
# property of the first.
