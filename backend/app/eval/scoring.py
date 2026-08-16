"""Deterministic scoring: no model, no randomness, no I/O (spec 06 §2).

Everything here is a pure function over (expected label, actual output,
evidence). That is what makes G5.1 assertable — re-scoring the same batch has
to produce byte-identical numbers, and a function that reads a clock, a
database, or a model cannot promise that.

The judge is deliberately elsewhere (`app/eval/judge.py`). Mixing a rubric
model into this module would make the deterministic half untestable without
one, and the whole reason for splitting them is that these numbers are the ones
you can argue about precisely.
"""

from dataclasses import dataclass
from typing import Any

# The three fields the fixture actually labels (D19 decision 5). Not
# `suggested_priority`: no priority label exists in eval_tickets.json, and
# scoring against a label nobody wrote is worse than not scoring.
SCORED_FIELDS = ("category", "urgency", "recommended_team")


@dataclass(frozen=True)
class FieldScore:
    expected: str | None
    actual: str | None
    correct: bool


def score_fields(expected: dict[str, Any], actual: dict[str, Any] | None) -> dict[str, FieldScore]:
    """Exact match per labelled field.

    A missing `actual` (the run failed before producing output) scores every
    field incorrect rather than skipping them. Dropping unanswered tickets from
    the denominator would make a crashing agent look accurate, which is the
    single most misleading thing an eval can do.
    """
    scores: dict[str, FieldScore] = {}
    for field in SCORED_FIELDS:
        want = expected.get(field)
        got = (actual or {}).get(field)
        scores[field] = FieldScore(
            expected=want,
            actual=got,
            # Both present and equal. `None == None` is not a correct answer.
            correct=want is not None and want == got,
        )
    return scores


def is_grounded(actual: dict[str, Any] | None, evidence: list[dict[str, Any]] | None) -> bool:
    """Did the answer cite at least one chunk this run actually retrieved?

    The same rule the graph enforces at runtime (D9), restated here because the
    eval must measure the property rather than trust that the pipeline enforced
    it. If the two ever disagree, that is a finding, not a rounding error.
    """
    citations = (actual or {}).get("citations") or []
    retrieved = {str(item.get("chunk_id")) for item in (evidence or [])}
    return any(str(citation.get("chunk_id")) in retrieved for citation in citations)


def retrieval_hit(
    grounding_references: list[dict[str, Any]] | None,
    evidence: list[dict[str, Any]] | None,
) -> bool | None:
    """hit@k: did retrieval surface the document the label is grounded in?

    Returns None when the fixture names no grounding reference — that ticket
    cannot contribute to hit@k either way, and averaging it in as a miss would
    punish the retriever for a gap in the answer key. `None` is excluded from
    the denominator by `summarize`.

    Matches on document identity, not chunk: the label points at a document and
    section, while evidence carries whichever chunks ranked. Requiring the exact
    chunk would measure chunking strategy rather than retrieval.

    Identity travels on the title, because `documents` has no external-reference
    column — the fixture says `MD-IT-001` and the uploaded title is
    "MD IT 001 vpn access policy", the loader having replaced the dashes. So
    both sides are normalised to alphanumerics before comparing, which survives
    dashes, spaces and case. This is genuinely fragile: retitle a document and
    hit@k silently drops. A `documents.external_ref` column is the real fix and
    is noted in ARCHITECTURE as deferred.
    """
    expected_docs = {
        _normalize(str(reference.get("doc_id")))
        for reference in (grounding_references or [])
        if reference and reference.get("doc_id")
    }
    if not expected_docs:
        return None
    found = [_normalize(str(item.get("document_title") or "")) for item in (evidence or [])]
    return any(doc and any(doc in candidate for candidate in found) for doc in expected_docs)


def _normalize(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scored results into the batch summary (G5.5).

    Metric keys are fixed and always present, even when a batch scored nothing:
    two batches are only comparable side by side if they have the same shape,
    and a key that appears only when non-empty makes the regression table
    ragged exactly when something went wrong.

    The denominator is every ticket attempted, including failed runs — the same
    basis `scripts/eval_baseline.py` settled on in Phase 3. An eval that quietly
    excludes its failures is measuring the happy path and calling it accuracy.
    """
    total = len(results)
    summary: dict[str, Any] = {
        "total_tickets": total,
        "scored_tickets": sum(1 for r in results if not r.get("failure_reason")),
        "failed_runs": sum(1 for r in results if r.get("failure_reason")),
    }

    for field in SCORED_FIELDS:
        correct = sum(1 for r in results if (r.get("scores") or {}).get(field, {}).get("correct"))
        summary[f"accuracy_{field}"] = _ratio(correct, total)

    summary["accuracy_overall"] = _ratio(
        sum(
            1
            for r in results
            if all((r.get("scores") or {}).get(f, {}).get("correct") for f in SCORED_FIELDS)
        ),
        total,
    )
    summary["grounded_rate"] = _ratio(
        sum(1 for r in results if (r.get("scores") or {}).get("grounded")), total
    )

    # hit@k skips tickets with no grounding reference — see `retrieval_hit`.
    measurable = [r for r in results if (r.get("scores") or {}).get("retrieval_hit") is not None]
    summary["retrieval_hit_at_k"] = _ratio(
        sum(1 for r in measurable if (r.get("scores") or {}).get("retrieval_hit")),
        len(measurable),
    )

    for name in ("resolution_quality", "citation_support"):
        judged = [
            (r.get("scores") or {}).get(name)
            for r in results
            if isinstance((r.get("scores") or {}).get(name), int | float)
        ]
        summary[f"judge_{name}_mean"] = round(sum(judged) / len(judged), 3) if judged else None
    summary["judged_tickets"] = sum(
        1
        for r in results
        if isinstance((r.get("scores") or {}).get("resolution_quality"), int | float)
    )
    return summary


def _ratio(numerator: int, denominator: int) -> float | None:
    """None, not 0.0, for an empty denominator.

    Zero would read as "nothing was correct" when the truth is "nothing was
    measured", and those two belong on opposite sides of any decision about
    whether a change helped.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)
