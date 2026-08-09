from __future__ import annotations

import uuid


def _triage_payload(
    chunk_id: uuid.UUID, **citation_overrides: object
) -> dict[str, object]:
    citation: dict[str, object] = {
        "chunk_id": str(chunk_id),
        "document_title": "VPN Access Policy",
        "page": 1,
        "section": "Recovery",
        "claim": "The recovery procedure applies.",
    }
    citation.update(citation_overrides)
    return {
        "summary": "Grounding probe",
        "category": "network_access",
        "urgency": "medium",
        "recommended_team": "IT Infrastructure",
        "suggested_priority": "P3",
        "recommended_resolution": "Follow the cited procedure.",
        "confidence": 0.8,
        "requires_approval": True,
        "citations": [citation],
    }


def test_citation_with_matching_chunk_but_fabricated_locator_is_not_grounded() -> None:
    from app.agents.schema import TriageResult
    from app.agents.validate import is_grounded, valid_citations

    chunk_id = uuid.uuid4()
    evidence = [
        {
            "chunk_id": str(chunk_id),
            "document_title": "VPN Access Policy",
            "page": 1,
            "section": "Recovery",
            "text": "Use the recovery procedure.",
        }
    ]
    result = TriageResult.model_validate(
        _triage_payload(
            chunk_id,
            document_title="Invented Security Policy",
            page=999,
            section="Fabricated section",
        )
    )

    assert valid_citations(result, evidence) == []
    assert not is_grounded(result, evidence)


def test_forged_chunk_id_cannot_satisfy_grounding() -> None:
    from app.agents.schema import TriageResult
    from app.agents.validate import is_grounded, valid_citations

    retrieved_chunk_id = uuid.uuid4()
    forged_chunk_id = uuid.uuid4()
    evidence = [
        {
            "chunk_id": str(retrieved_chunk_id),
            "document_title": "VPN Access Policy",
            "page": 1,
            "section": "Recovery",
        }
    ]
    result = TriageResult.model_validate(_triage_payload(forged_chunk_id))

    assert valid_citations(result, evidence) == []
    assert not is_grounded(result, evidence)
