from __future__ import annotations

import json
from pathlib import Path

from conftest import Phase1Client, retrieval_results_from


def _retrieval_checks(path: Path) -> list[dict[str, object]]:
    assert path.is_file(), "G1.2 requires fixtures/retrieval_checks.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("checks")
    assert isinstance(
        payload, list
    ), "retrieval_checks.json must be a list or an object with a 'checks' list"
    assert len(payload) == 5, "G1.2 requires exactly five canned retrieval checks"
    for index, check in enumerate(payload):
        assert isinstance(check, dict), f"retrieval check {index} must be an object"
        assert isinstance(check.get("query"), str) and str(check["query"]).strip()
        expected = _expected_doc_ids(check)
        assert (
            expected
        ), f"retrieval check {index} requires expected_doc_id or expected_doc_ids"
        assert all(
            isinstance(doc_id, str) and doc_id.startswith("MD-IT-")
            for doc_id in expected
        )
    return payload


def _expected_doc_ids(check: dict[str, object]) -> list[str]:
    plural = check.get("expected_doc_ids")
    if isinstance(plural, list):
        return [str(doc_id) for doc_id in plural]
    singular = check.get("expected_doc_id")
    return [singular] if isinstance(singular, str) else []


def _assert_citation_contract(result: dict[str, object]) -> None:
    required = {
        "text",
        "score",
        "document_title",
        "version",
        "page",
        "section",
        "chunk_id",
    }
    assert (
        required <= result.keys()
    ), f"retrieval result is missing citation fields: {sorted(required - result.keys())}"
    assert isinstance(result["text"], str) and result["text"].strip()
    assert isinstance(result["score"], int | float)
    assert (
        isinstance(result["document_title"], str) and result["document_title"].strip()
    )
    assert isinstance(result["version"], str) and result["version"].strip()
    assert isinstance(result["chunk_id"], str) and result["chunk_id"].strip()
    assert result["page"] is None or isinstance(result["page"], int)
    assert result["section"] is None or isinstance(result["section"], str)


def test_g1_2_retrieval_checks_fixture_defines_five_canned_queries(
    repository_root: Path,
) -> None:
    _retrieval_checks(repository_root / "fixtures" / "retrieval_checks.json")


def test_g1_2_canned_queries_return_expected_documents_in_top_three(
    repository_root: Path,
    phase1_client: Phase1Client,
    org_a_id: str,
    ingested_corpus: dict[str, str],
) -> None:
    del ingested_corpus  # the fixture guarantees the complete corpus is ready
    checks = _retrieval_checks(repository_root / "fixtures" / "retrieval_checks.json")

    for check in checks:
        response = phase1_client.retrieve(org_a_id, str(check["query"]), k=3)
        results = retrieval_results_from(response)
        assert 0 < len(results) <= 3
        for result in results:
            _assert_citation_contract(result)
        scores = [float(result["score"]) for result in results]
        assert scores == sorted(
            scores, reverse=True
        ), f"results are not ranked by descending cosine similarity: {scores}"

        returned_titles = [str(result["document_title"]).lower() for result in results]
        expected_ids = _expected_doc_ids(check)
        assert any(
            expected_id.lower() in title
            for expected_id in expected_ids
            for title in returned_titles
        ), (
            f"query {check['query']!r} expected one of {expected_ids} in top 3; "
            f"got titles {returned_titles}"
        )
