from __future__ import annotations

import os
import re
import time
from typing import Any
from uuid import uuid4

import pytest

from .conftest import (
    ROLE_NAMES,
    Phase4Client,
    PrincipalToken,
    object_body,
    response_detail,
)

HTTP_METHODS = {"delete", "get", "patch", "post", "put"}
PATH_PARAMETER = re.compile(r"\{[^}]+\}")


def _login_paths(client: Phase4Client) -> set[str]:
    configured = os.environ.get("PHASE4_LOGIN_PATHS", "")
    return {
        client.token_path,
        "/api/login",
        "/api/auth/callback",
        *(path.strip() for path in configured.split(",") if path.strip()),
    }


def _is_login_path(path: str, client: Phase4Client) -> bool:
    normalized = path.rstrip("/")
    return path in _login_paths(client) or normalized.endswith(("/login", "/callback"))


def _concrete_path(path: str) -> str:
    return PATH_PARAMETER.sub("00000000-0000-0000-0000-000000000000", path)


def _api_operations(schema: dict[str, Any]) -> list[tuple[str, str]]:
    paths = schema.get("paths")
    assert isinstance(paths, dict), "OpenAPI schema has no route table"
    operations: list[tuple[str, str]] = []
    for path, route in paths.items():
        if not isinstance(path, str) or not path.startswith("/api"):
            continue
        assert isinstance(route, dict), route
        for method in route:
            if method.lower() in HTTP_METHODS:
                operations.append((method.upper(), path))
    return sorted(operations)


def test_g4_1_route_table_requires_authentication(
    phase4_client: Phase4Client,
) -> None:
    """Every shipping and dev-only /api operation is discovered, not hand-picked."""
    schema_response = phase4_client.request("GET", "/openapi.json")
    assert schema_response.status == 200, response_detail(schema_response)
    assert isinstance(schema_response.body, dict), response_detail(schema_response)

    checked: list[tuple[str, str]] = []
    for method, template in _api_operations(schema_response.body):
        if template == "/api/health" or _is_login_path(template, phase4_client):
            continue
        response = phase4_client.request(method, _concrete_path(template))
        assert response.status == 401, (
            f"unauthenticated {method} {template} must return 401, not "
            f"{response_detail(response)}"
        )
        checked.append((method, template))

    assert checked, "route-table walk found no protected /api operations"


def test_g4_1_health_and_local_login_are_the_only_working_exemptions(
    phase4_client: Phase4Client,
) -> None:
    assert phase4_client.request("GET", "/api/health").status == 200
    token = phase4_client.issue_token(
        email=f"not-seeded-{uuid4()}@example.test",
        subject=f"phase4-unlinked|{uuid4()}",
    )
    assert token


@pytest.mark.parametrize("authorization", ["Bearer", "Bearer not-a-jwt", "Basic abc"])
def test_g4_1_malformed_credentials_are_unauthorized(
    phase4_client: Phase4Client,
    authorization: str,
) -> None:
    response = phase4_client.request(
        "GET", "/api/me", headers={"Authorization": authorization}
    )
    assert response.status == 401, response_detail(response)


def test_g4_1_expired_token_is_unauthorized(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    principal = phase4_principals["a"]["operator"]
    token = phase4_client.issue_token(
        email=principal.email,
        subject=principal.subject,
        expires_in_seconds=1,
    )
    time.sleep(2)
    response = phase4_client.request("GET", "/api/me", token=token)
    assert response.status == 401, response_detail(response)


def test_g4_1_unknown_subject_cannot_self_provision(
    phase4_client: Phase4Client,
) -> None:
    marker = uuid4()
    token = phase4_client.issue_token(
        email=f"unknown-{marker}@example.test",
        subject=f"phase4-unknown|{marker}",
    )
    response = phase4_client.request("GET", "/api/me", token=token)
    assert response.status == 403, response_detail(response)


def test_g4_1_me_returns_database_identity_roles_and_org(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    principal = phase4_principals["a"]["all_roles"]
    response = phase4_client.request("GET", "/api/me", token=principal.access_token)
    assert response.status == 200, response_detail(response)
    body = object_body(response, "user", "principal")
    assert body.get("id") == principal.user_id, body
    assert body.get("email") == principal.email, body
    roles = body.get("roles")
    assert isinstance(roles, list), body
    assert set(roles) == set(ROLE_NAMES), body
    org = body.get("org", body.get("organization"))
    if isinstance(org, dict):
        assert org.get("id") == principal.org_id, body
    else:
        assert body.get("org_id") == principal.org_id, body
