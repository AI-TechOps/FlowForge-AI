from __future__ import annotations

from uuid import uuid4

from .conftest import (
    Phase1Client,
    document_id_from,
    response_detail,
    retrieval_results_from,
    wait_for_document_status,
)


def _upload_tenant_probe(
    client: Phase1Client,
    *,
    org_id: str,
    marker: str,
    title: str,
) -> str:
    response = client.upload_bytes(
        org_id=org_id,
        filename=f"{marker}.txt",
        title=title,
        content=(
            f"Tenant-isolation acceptance probe. Unique marker: {marker}. "
            "This content belongs to exactly one organization."
        ).encode(),
    )
    assert response.status == 202, response_detail(response)
    document_id = document_id_from(response)
    status, _ = wait_for_document_status(
        client,
        org_id=org_id,
        document_id=document_id,
        terminal_statuses={"ready", "failed"},
        timeout=60,
    )
    assert status["status"] == "ready", status
    return document_id


def test_g1_3_retrieval_never_crosses_organization_boundaries(
    phase1_client: Phase1Client,
    tenant_probe_organization_ids: tuple[str, str],
) -> None:
    org_a_id, org_b_id = tenant_probe_organization_ids
    marker_a = f"org-a-{uuid4().hex}"
    marker_b = f"org-b-{uuid4().hex}"
    title_a = f"Tenant A Probe {marker_a}"
    title_b = f"Tenant B Probe {marker_b}"
    _upload_tenant_probe(
        phase1_client,
        org_id=org_a_id,
        marker=marker_a,
        title=title_a,
    )
    _upload_tenant_probe(
        phase1_client,
        org_id=org_b_id,
        marker=marker_b,
        title=title_b,
    )

    results_a = retrieval_results_from(phase1_client.retrieve(org_a_id, marker_b, k=20))
    results_b = retrieval_results_from(phase1_client.retrieve(org_b_id, marker_a, k=20))

    titles_a = {str(result.get("document_title", "")) for result in results_a}
    titles_b = {str(result.get("document_title", "")) for result in results_b}
    assert not any(marker_b in title for title in titles_a), (
        f"org A retrieved org B's document: {sorted(titles_a)}"
    )
    assert not any(marker_a in title for title in titles_b), (
        f"org B retrieved org A's document: {sorted(titles_b)}"
    )
    assert any(marker_a in title for title in titles_a), (
        "org A must still retrieve its own probe document"
    )
    assert any(marker_b in title for title in titles_b), (
        "org B must still retrieve its own probe document"
    )

    chunk_ids_a = {str(result.get("chunk_id")) for result in results_a}
    chunk_ids_b = {str(result.get("chunk_id")) for result in results_b}
    assert chunk_ids_a.isdisjoint(chunk_ids_b), (
        "the same stored chunk was visible to both organizations"
    )
