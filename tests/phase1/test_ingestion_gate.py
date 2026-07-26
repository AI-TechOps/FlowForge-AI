from __future__ import annotations

from pathlib import Path

from conftest import (
    Phase1Client,
    documents_from,
    locate_corpus_paths,
    retrieval_results_from,
)


def test_g1_1_meridian_corpus_contains_all_ingestion_formats(
    repository_root: Path,
) -> None:
    corpus_paths, missing = locate_corpus_paths(repository_root)
    assert not missing, (
        "G1.1 requires the ten approved Meridian corpus fixtures: " + "; ".join(missing)
    )
    suffixes = [path.suffix.lower() for path in corpus_paths.values()]
    assert len(corpus_paths) == 10
    assert suffixes.count(".pdf") >= 2
    assert suffixes.count(".txt") >= 1
    assert ".md" in suffixes


def test_g1_1_every_fixture_document_is_ready_with_chunks(
    phase1_client: Phase1Client,
    org_a_id: str,
    ingested_corpus: dict[str, str],
) -> None:
    response = phase1_client.list_documents(org_a_id)
    documents = documents_from(response)
    documents_by_id = {
        str(document.get("id", document.get("document_id"))): document
        for document in documents
    }

    for doc_id, document_id in ingested_corpus.items():
        assert (
            document_id in documents_by_id
        ), f"{doc_id} ({document_id}) is missing from GET /api/documents"
        document = documents_by_id[document_id]
        assert document.get("status") == "ready"
        chunk_count = document.get("chunk_count")
        assert (
            isinstance(chunk_count, int) and chunk_count > 0
        ), f"{doc_id} must report chunk_count > 0: {document!r}"


def test_g1_1_pdf_and_markdown_chunks_preserve_source_metadata(
    phase1_client: Phase1Client,
    org_a_id: str,
    ingested_corpus: dict[str, str],
    corpus_paths: dict[str, Path],
) -> None:
    for doc_id, path in corpus_paths.items():
        if path.suffix.lower() not in {".pdf", ".md"}:
            continue
        response = phase1_client.retrieve(org_a_id, doc_id, k=10)
        results = retrieval_results_from(response)
        matching = [
            result
            for result in results
            if doc_id.lower() in str(result.get("document_title", "")).lower()
        ]
        assert matching, f"retrieval could not find uploaded fixture {doc_id}"
        if path.suffix.lower() == ".pdf":
            assert any(
                isinstance(result.get("page"), int) and result["page"] >= 1
                for result in matching
            ), f"{doc_id} PDF chunks must preserve a 1-based page number"
        else:
            assert any(
                isinstance(result.get("section"), str)
                and bool(str(result["section"]).strip())
                for result in matching
            ), f"{doc_id} Markdown chunks must preserve nearest-heading sections"
