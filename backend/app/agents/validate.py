"""Schema and grounding enforcement — the rules that make output trustworthy.

Two separate guarantees, both enforced in code rather than requested in a
prompt (D9):

1. **Schema/enum validity** — output that does not parse into `TriageResult`,
   or that names a value outside the taxonomy, never reaches `completed`.
2. **Grounding** — a recommendation is not grounded unless at least one
   citation points at a chunk this run actually retrieved. A model naming a
   plausible-sounding document is not evidence.
"""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.agents.schema import TriageResult


@dataclass(frozen=True)
class ValidationOutcome:
    result: TriageResult | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.result is not None


def parse_triage_result(raw: str) -> ValidationOutcome:
    """Parse raw model text into a validated TriageResult.

    Enum violations surface here too: `category`/`urgency`/`suggested_priority`/
    `recommended_team` are typed as taxonomy enums, so an out-of-set value is a
    validation error, not a silently accepted string (G2.3).
    """
    text = _strip_code_fence(raw.strip())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return ValidationOutcome(None, f"output is not valid JSON: {exc}")

    if not isinstance(payload, dict):
        return ValidationOutcome(None, f"expected a JSON object, got {type(payload).__name__}")

    try:
        return ValidationOutcome(TriageResult.model_validate(payload), None)
    except ValidationError as exc:
        return ValidationOutcome(None, _compact_errors(exc))


def _strip_code_fence(text: str) -> str:
    """Tolerate ```json fences from models that ignore the format directive.

    This is presentation forgiveness only — the content still has to validate.
    """
    if not text.startswith("```"):
        return text
    body = text.split("\n", 1)[-1]
    return body.rsplit("```", 1)[0].strip() if "```" in body else body.strip()


def _compact_errors(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:6]:
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def valid_citations(result: TriageResult, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Citations whose chunk_id was actually retrieved, with trusted locators.

    The model chooses only two things: which chunk supports the claim, and what
    the claim is. `document_title`, `page` and `section` are overwritten from
    the retrieved chunk, because a citation naming a real chunk but an invented
    document and page 999 used to pass grounding and reach the run detail as
    though it were provenance (Codex Phase 2 finding 5).

    Overwriting rather than discarding the citation is deliberate: a small
    local model that picks the right chunk but hallucinates a page number still
    produces a correctly-attributed citation, instead of failing the whole run
    as ungrounded.
    """
    retrieved = {str(chunk.get("chunk_id")): chunk for chunk in evidence}
    grounded: list[dict[str, Any]] = []
    for citation in result.citations:
        chunk = retrieved.get(str(citation.chunk_id))
        if chunk is None:
            continue
        payload = citation.model_dump(mode="json")
        payload["document_title"] = chunk.get("document_title")
        payload["page"] = chunk.get("page")
        payload["section"] = chunk.get("section")
        grounded.append(payload)
    return grounded


def is_grounded(result: TriageResult, evidence: list[dict[str, Any]]) -> bool:
    """The grounding rule: no valid citation, not grounded (D9)."""
    return len(valid_citations(result, evidence)) > 0
