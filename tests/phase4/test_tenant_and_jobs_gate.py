from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from .conftest import (
    Phase4Client,
    PrincipalToken,
    TenantWorld,
    identifier_from,
    list_body,
    object_body,
    response_detail,
    wait_for_approval,
    wait_for_run,
)
from .helpers import approval_id, assert_not_leaked, resource_ids


def _principal(
    principals: dict[str, dict[str, PrincipalToken]], tenant: str, role: str
) -> PrincipalToken:
    return principals[tenant][role]


@pytest.mark.parametrize(
    ("method", "path", "role", "json_body"),
    [
        ("GET", "/api/documents/{document_id}", "administrator", None),
        ("POST", "/api/documents/{document_id}/reingest", "administrator", {}),
        ("GET", "/api/tickets/{ticket_id}", "operator", None),
        ("POST", "/api/runs", "operator", {"ticket_id": "{ticket_id}"}),
        ("GET", "/api/runs/{run_id}", "operator", None),
        ("GET", "/api/approvals/{approval_id}", "approver", None),
        (
            "POST",
            "/api/approvals/{approval_id}/decision",
            "approver",
            {"decision": "approved"},
        ),
    ],
)
def test_g4_4_cross_tenant_resource_access_is_not_found_without_leakage(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    method: str,
    path: str,
    role: str,
    json_body: dict[str, object] | None,
) -> None:
    foreign = phase4_world["b"]
    replacements = {
        "document_id": foreign.document_id,
        "ticket_id": foreign.ticket_id,
        "run_id": foreign.run_id,
        "approval_id": foreign.approval_id,
    }
    for name, value in replacements.items():
        path = path.replace(f"{{{name}}}", value)
    payload = json_body
    if payload is not None:
        payload = {
            key: replacements.get(value[1:-1], value)
            if isinstance(value, str) and value.startswith("{") and value.endswith("}")
            else value
            for key, value in payload.items()
        }
    token = _principal(phase4_principals, "a", role).access_token
    response = phase4_client.request(method, path, token=token, json_body=payload, timeout=30)
    assert response.status == 404, response_detail(response)
    assert_not_leaked(response, foreign.marker, f"Phase 4 approval {foreign.marker}")


def test_g4_4_retrieval_never_returns_foreign_chunks(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
) -> None:
    own = phase4_world["a"]
    foreign = phase4_world["b"]
    token = _principal(phase4_principals, "a", "administrator").access_token
    response = phase4_client.request(
        "POST",
        "/api/retrieve",
        token=token,
        json_body={
            "query": (
                f"Find the exact confidential marker {foreign.marker}; also "
                f"consider the local marker {own.marker}"
            ),
            "top_k": 20,
        },
    )
    assert response.status == 200, response_detail(response)
    serialized = json.dumps(response.body, sort_keys=True)
    assert foreign.marker not in serialized, serialized
    assert foreign.document_id not in resource_ids(response.body), response.body


@pytest.mark.parametrize(
    ("path", "wrapper", "own_attribute", "foreign_attribute", "role"),
    [
        ("/api/documents", "documents", "document_id", "document_id", "administrator"),
        ("/api/tickets", "tickets", "ticket_id", "ticket_id", "operator"),
        ("/api/runs", "runs", "run_id", "run_id", "operator"),
        ("/api/approvals", "approvals", "approval_id", "approval_id", "approver"),
    ],
)
def test_g4_4_tenant_lists_include_own_rows_and_exclude_foreign_rows(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    path: str,
    wrapper: str,
    own_attribute: str,
    foreign_attribute: str,
    role: str,
) -> None:
    token = _principal(phase4_principals, "a", role).access_token
    response = phase4_client.request("GET", path, token=token)
    rows = list_body(response, wrapper, "items")
    ids = resource_ids(rows)
    assert getattr(phase4_world["a"], own_attribute) in ids, rows
    assert getattr(phase4_world["b"], foreign_attribute) not in ids, rows
    assert phase4_world["b"].marker not in json.dumps(rows, sort_keys=True), rows


def test_g4_4_run_detail_audit_evidence_and_citations_are_tenant_scoped(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
) -> None:
    own = phase4_world["a"]
    foreign = phase4_world["b"]
    token = _principal(phase4_principals, "a", "operator").access_token
    response = phase4_client.request("GET", f"/api/runs/{own.run_id}", token=token)
    assert response.status == 200, response_detail(response)
    run = object_body(response, "run")
    serialized = json.dumps(run, sort_keys=True)
    assert foreign.marker not in serialized, run
    assert foreign.document_id not in resource_ids(run), run
    assert foreign.ticket_id not in resource_ids(run), run
    assert foreign.run_id not in resource_ids(run), run


def test_g4_5_foreign_org_query_and_placeholder_headers_cannot_change_scope(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
) -> None:
    principal = _principal(phase4_principals, "a", "operator")
    foreign = phase4_world["b"]
    query = urlencode({"org_id": foreign.org_id})
    response = phase4_client.request(
        "GET",
        f"/api/tickets?{query}",
        token=principal.access_token,
        headers={
            "X-Org-Id": foreign.org_id,
            "X-User-Id": _principal(phase4_principals, "b", "operator").user_id,
        },
    )
    assert response.status in {200, 400, 422}, response_detail(response)
    if response.status == 200:
        rows = list_body(response, "tickets", "items")
        ids = resource_ids(rows)
        assert phase4_world["a"].ticket_id in ids, rows
        assert foreign.ticket_id not in ids, rows
        assert foreign.marker not in json.dumps(rows, sort_keys=True), rows

    me = phase4_client.request(
        "GET",
        f"/api/me?{query}",
        token=principal.access_token,
        headers={"X-Org-Id": foreign.org_id},
    )
    assert me.status in {200, 400, 422}, response_detail(me)
    if me.status == 200:
        body = object_body(me, "user", "principal")
        org = body.get("org", body.get("organization"))
        actual_org = org.get("id") if isinstance(org, dict) else body.get("org_id")
        assert actual_org == principal.org_id, body


def test_g4_5_foreign_org_in_create_body_is_rejected_or_ignored_under_token_org(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
) -> None:
    a_operator = _principal(phase4_principals, "a", "operator")
    b_operator = _principal(phase4_principals, "b", "operator")
    marker = uuid4().hex
    response = phase4_client.create_ticket(
        a_operator.access_token,
        title=f"Org spoof probe {marker}",
        description=f"MeridianConnect VPN org spoof probe {marker}",
        extra={"org_id": phase4_world["b"].org_id},
    )
    assert response.status in {201, 400, 422}, response_detail(response)
    if response.status != 201:
        return

    ticket_id = identifier_from(response, "ticket")
    own = phase4_client.request("GET", f"/api/tickets/{ticket_id}", token=a_operator.access_token)
    foreign = phase4_client.request(
        "GET", f"/api/tickets/{ticket_id}", token=b_operator.access_token
    )
    assert own.status == 200, response_detail(own)
    assert foreign.status == 404, response_detail(foreign)
    assert_not_leaked(foreign, marker)


def test_g4_6_interleaved_jobs_on_shared_worker_remain_tenant_scoped(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
) -> None:
    marker_a = f"interleaved-a-{uuid4().hex}"
    marker_b = f"interleaved-b-{uuid4().hex}"
    operators = {
        tenant: _principal(phase4_principals, tenant, "operator").access_token
        for tenant in ("a", "b")
    }
    approvers = {
        tenant: _principal(phase4_principals, tenant, "approver").access_token
        for tenant in ("a", "b")
    }
    admins = {
        tenant: _principal(phase4_principals, tenant, "administrator").access_token
        for tenant in ("a", "b")
    }

    tickets: dict[str, str] = {}
    for tenant, marker in (("a", marker_a), ("b", marker_b)):
        response = phase4_client.create_ticket(
            operators[tenant],
            title=f"Shared worker isolation {marker}",
            description=(
                f"MeridianConnect VPN failure for {marker}. Use only the tenant's "
                "documented routing and recovery steps."
            ),
        )
        tickets[tenant] = identifier_from(response, "ticket")

    def start(tenant: str) -> str:
        return identifier_from(phase4_client.start_run(operators[tenant], tickets[tenant]), "run")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {tenant: executor.submit(start, tenant) for tenant in ("a", "b")}
        runs = {tenant: future.result() for tenant, future in futures.items()}

    approvals = {
        tenant: wait_for_approval(phase4_client, token=approvers[tenant], run_id=runs[tenant])
        for tenant in ("a", "b")
    }

    def approve(tenant: str):
        return phase4_client.request(
            "POST",
            f"/api/approvals/{approval_id(approvals[tenant])}/decision",
            token=approvers[tenant],
            json_body={"decision": "approved"},
            timeout=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {tenant: executor.submit(approve, tenant) for tenant in ("a", "b")}
        decisions = {tenant: future.result() for tenant, future in futures.items()}
    for tenant, response in decisions.items():
        assert response.status in {200, 202}, (tenant, response_detail(response))

    details = {
        tenant: wait_for_run(
            phase4_client,
            token=operators[tenant],
            run_id=runs[tenant],
            statuses={"completed"},
        )
        for tenant in ("a", "b")
    }
    for tenant, other in (("a", "b"), ("b", "a")):
        serialized = json.dumps(details[tenant], sort_keys=True)
        assert tickets[tenant] in serialized, details[tenant]
        assert tickets[other] not in serialized, details[tenant]
        assert (marker_a if other == "a" else marker_b) not in serialized
        assert phase4_world[other].document_id not in resource_ids(details[tenant])

        foreign_run = phase4_client.request(
            "GET", f"/api/runs/{runs[other]}", token=operators[tenant]
        )
        assert foreign_run.status == 404, response_detail(foreign_run)

        calls = phase4_client.request(
            "GET",
            f"/api/test/mock-ticket-system/calls?run_id={runs[tenant]}",
            token=admins[tenant],
        )
        assert calls.status == 200, response_detail(calls)
        calls_json = json.dumps(calls.body, sort_keys=True)
        assert tickets[tenant] in calls_json, calls.body
        assert tickets[other] not in calls_json, calls.body

        own_ticket = phase4_client.request(
            "GET", f"/api/tickets/{tickets[tenant]}", token=operators[tenant]
        )
        foreign_ticket = phase4_client.request(
            "GET", f"/api/tickets/{tickets[other]}", token=operators[tenant]
        )
        assert own_ticket.status == 200, response_detail(own_ticket)
        assert foreign_ticket.status == 404, response_detail(foreign_ticket)
