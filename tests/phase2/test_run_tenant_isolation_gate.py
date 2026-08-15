from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from .conftest import (
    TRIAGE_SUCCESS_STATUSES,
    Phase2Client,
    audit_entries_from,
    document_id_from,
    evidence_from,
    response_detail,
    run_id_from,
    ticket_id_from,
    wait_for_document_ready,
    wait_for_run,
)


def _results_from(response_body: object) -> list[dict[str, object]]:
    payload = response_body
    if isinstance(payload, dict):
        payload = payload.get("results")
    assert isinstance(payload, list)
    assert all(isinstance(result, dict) for result in payload)
    return payload


def _chunk_ids(items: list[dict[str, object]]) -> set[str]:
    return {
        str(item["chunk_id"])
        for item in items
        if isinstance(item.get("chunk_id"), str) and item["chunk_id"]
    }


def test_g2_6_run_cannot_read_ticket_or_retrieve_evidence_from_another_org(
    tmp_path: Path,
    phase2_client: Phase2Client,
    isolation_org_ids: tuple[str, str],
) -> None:
    org_a_id, org_b_id = isolation_org_ids
    marker_a = f"tenant-a-{uuid4().hex}"
    marker_b = f"tenant-b-{uuid4().hex}"
    doc_a = tmp_path / f"{marker_a}.txt"
    doc_b = tmp_path / f"{marker_b}.txt"
    doc_a.write_text(
        f"Organization A support evidence. Unique marker {marker_a}.",
        encoding="utf-8",
    )
    doc_b.write_text(
        f"Organization B confidential support evidence. Unique marker {marker_b}.",
        encoding="utf-8",
    )

    document_a_id = document_id_from(
        phase2_client.upload_path(org_a_id, doc_a, f"Tenant A Probe {marker_a}")
    )
    document_b_id = document_id_from(
        phase2_client.upload_path(org_b_id, doc_b, f"Tenant B Probe {marker_b}")
    )
    wait_for_document_ready(
        phase2_client,
        org_id=org_a_id,
        document_id=document_a_id,
    )
    wait_for_document_ready(
        phase2_client,
        org_id=org_b_id,
        document_id=document_b_id,
    )

    b_retrieval = phase2_client.retrieve(org_b_id, marker_b)
    assert b_retrieval.status == 200, response_detail(b_retrieval)
    b_results = _results_from(b_retrieval.body)
    b_chunk_ids = _chunk_ids(b_results)
    assert b_chunk_ids, "the org B probe must exist before testing isolation"

    ticket_b = phase2_client.create_ticket(
        org_b_id,
        title=f"Tenant B ticket {marker_b}",
        description=f"Only organization B may read this ticket: {marker_b}.",
    )
    ticket_b_id = ticket_id_from(ticket_b)

    cross_org_read = phase2_client.get_ticket(org_a_id, ticket_b_id)
    assert cross_org_read.status in {403, 404}, response_detail(cross_org_read)
    cross_org_triage = phase2_client.triage(org_a_id, ticket_b_id)
    assert cross_org_triage.status in {403, 404}, response_detail(cross_org_triage)

    ticket_a = phase2_client.create_ticket(
        org_a_id,
        title=f"Tenant A isolation run {marker_a}",
        description=(
            f"Use organization A evidence {marker_a}. The query also mentions the "
            f"unavailable organization B marker {marker_b}."
        ),
    )
    ticket_a_id = ticket_id_from(ticket_a)
    run_id = run_id_from(phase2_client.triage(org_a_id, ticket_a_id))
    run = wait_for_run(phase2_client, org_id=org_a_id, run_id=run_id)
    assert run["status"] in TRIAGE_SUCCESS_STATUSES, run

    evidence = evidence_from(run)
    evidence_chunk_ids = _chunk_ids(evidence)
    assert evidence_chunk_ids, run
    assert evidence_chunk_ids.isdisjoint(b_chunk_ids), (
        f"org A run retrieved org B chunks: {evidence_chunk_ids & b_chunk_ids}"
    )
    evidence_json = json.dumps(evidence)
    assert f"Tenant B Probe {marker_b}" not in evidence_json
    assert f"Tenant A Probe {marker_a}" in evidence_json

    output = run.get("output")
    assert isinstance(output, dict)
    citations = output.get("citations")
    assert isinstance(citations, list) and citations
    citation_chunk_ids = _chunk_ids(citations)
    assert citation_chunk_ids.isdisjoint(b_chunk_ids), (
        f"org A output cited org B chunks: {citation_chunk_ids & b_chunk_ids}"
    )
    assert ticket_b_id not in json.dumps(audit_entries_from(run)), (
        "org A audit data leaked the org B ticket read probe"
    )
