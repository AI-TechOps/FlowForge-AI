from __future__ import annotations

from uuid import uuid4

import pytest

from .conftest import (
    Phase4Client,
    PrincipalToken,
    TenantWorld,
    create_pending_approval,
    identifier_from,
    response_detail,
    wait_for_approval,
    wait_for_run,
)
from .helpers import approval_id, assert_allowed, assert_forbidden

ROLES = ("administrator", "operator", "approver")


def _token(principals: dict[str, dict[str, PrincipalToken]], role: str) -> str:
    return principals["a"][role].access_token


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_documents_post_and_get_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    role: str,
) -> None:
    token = _token(phase4_principals, role)
    marker = uuid4().hex
    responses = [
        phase4_client.upload_bytes(
            token,
            filename=f"rbac-{marker}.md",
            title=f"RBAC document {marker}",
            content=f"Phase 4 RBAC marker {marker}".encode(),
        ),
        phase4_client.request("GET", "/api/documents", token=token),
    ]
    if role == "administrator":
        assert_allowed(responses)
    else:
        assert_forbidden(responses)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_retrieve_post_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    role: str,
) -> None:
    response = phase4_client.request(
        "POST",
        "/api/retrieve",
        token=_token(phase4_principals, role),
        json_body={"query": "MeridianConnect VPN recovery", "top_k": 3},
    )
    if role == "administrator":
        assert_allowed(response, statuses={200})
    else:
        assert_forbidden(response)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_tickets_post_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    role: str,
) -> None:
    marker = uuid4().hex
    response = phase4_client.create_ticket(
        _token(phase4_principals, role),
        title=f"RBAC create ticket {marker}",
        description=f"MeridianConnect VPN incident {marker}",
    )
    if role in {"administrator", "operator"}:
        assert_allowed(response, statuses={201})
    else:
        assert_forbidden(response)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_tickets_get_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    role: str,
) -> None:
    token = _token(phase4_principals, role)
    responses = [
        phase4_client.request("GET", "/api/tickets", token=token),
        phase4_client.request("GET", f"/api/tickets/{phase4_world['a'].ticket_id}", token=token),
    ]
    assert_allowed(responses, statuses={200})


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_runs_post_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    role: str,
) -> None:
    response = phase4_client.start_run(_token(phase4_principals, role), phase4_world["a"].ticket_id)
    if role in {"administrator", "operator"}:
        assert_allowed(response)
    else:
        assert_forbidden(response)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_runs_get_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    role: str,
) -> None:
    token = _token(phase4_principals, role)
    responses = [
        phase4_client.request("GET", "/api/runs", token=token),
        phase4_client.request("GET", f"/api/runs/{phase4_world['a'].run_id}", token=token),
    ]
    assert_allowed(responses, statuses={200})


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_approvals_get_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    role: str,
) -> None:
    token = _token(phase4_principals, role)
    responses = [
        phase4_client.request("GET", "/api/approvals", token=token),
        phase4_client.request(
            "GET",
            f"/api/approvals/{phase4_world['a'].approval_id}",
            token=token,
        ),
    ]
    if role in {"administrator", "approver"}:
        assert_allowed(responses, statuses={200})
    else:
        assert_forbidden(responses)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_and_g4_3_approval_decision_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    role: str,
) -> None:
    principals = phase4_principals["a"]
    _, _, approval = create_pending_approval(
        phase4_client,
        operator_token=principals["operator"].access_token,
        approver_token=principals["approver"].access_token,
        marker=f"decision-matrix-{role}-{uuid4().hex}",
    )
    response = phase4_client.request(
        "POST",
        f"/api/approvals/{approval_id(approval)}/decision",
        token=principals[role].access_token,
        json_body={"decision": "approved"},
        timeout=30,
    )
    if role == "approver":
        assert_allowed(response)
    else:
        assert_forbidden(response)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_test_routes_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
    role: str,
) -> None:
    response = phase4_client.request(
        "GET",
        f"/api/test/mock-ticket-system/calls?run_id={phase4_world['a'].run_id}",
        token=_token(phase4_principals, role),
    )
    if role == "administrator":
        assert_allowed(response, statuses={200})
    else:
        assert_forbidden(response)


@pytest.mark.parametrize("role", ROLES)
def test_g4_2_me_get_matrix_cell(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    role: str,
) -> None:
    response = phase4_client.request("GET", "/api/me", token=_token(phase4_principals, role))
    assert_allowed(response, statuses={200})


def test_g4_3_operator_who_triggered_run_cannot_decide_it(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    operator = phase4_principals["a"]["operator"].access_token
    approver = phase4_principals["a"]["approver"].access_token
    _, _, approval = create_pending_approval(
        phase4_client,
        operator_token=operator,
        approver_token=approver,
        marker=f"triggering-operator-{uuid4().hex}",
    )
    response = phase4_client.request(
        "POST",
        f"/api/approvals/{approval_id(approval)}/decision",
        token=operator,
        json_body={"decision": "approved"},
    )
    assert response.status == 403, response_detail(response)


def test_g4_3_agent_or_system_identity_cannot_decide(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
    phase4_world: dict[str, TenantWorld],
) -> None:
    marker = uuid4()
    machine_token = phase4_client.issue_token(
        email=f"worker-{marker}@example.test",
        subject=f"system|worker|{marker}",
    )
    response = phase4_client.request(
        "POST",
        f"/api/approvals/{phase4_world['a'].approval_id}/decision",
        token=machine_token,
        json_body={"decision": "approved"},
    )
    assert response.status == 403, response_detail(response)


def test_g4_3_triggering_user_can_approve_only_with_explicit_approver_grant(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    principal = phase4_principals["a"]["all_roles"]
    marker = uuid4().hex
    ticket = phase4_client.create_ticket(
        principal.access_token,
        title=f"Explicit approver grant {marker}",
        description=f"MeridianConnect VPN recovery needed. Marker {marker}.",
    )
    ticket_id = identifier_from(ticket, "ticket")
    run_id = identifier_from(phase4_client.start_run(principal.access_token, ticket_id), "run")
    approval = wait_for_approval(phase4_client, token=principal.access_token, run_id=run_id)
    response = phase4_client.request(
        "POST",
        f"/api/approvals/{approval_id(approval)}/decision",
        token=principal.access_token,
        json_body={"decision": "approved"},
        timeout=30,
    )
    assert_allowed(response)
    completed = wait_for_run(
        phase4_client,
        token=principal.access_token,
        run_id=run_id,
        statuses={"completed"},
    )
    assert completed.get("status") == "completed", completed
