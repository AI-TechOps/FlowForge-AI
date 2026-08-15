from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TOKEN_PATH = "/api/dev/token"
ROLE_NAMES = ("administrator", "operator", "approver")
TRIAGE_SETTLED_STATUSES = {"awaiting_approval", "completed", "failed"}
TERMINAL_RUN_STATUSES = {"completed", "rejected", "failed"}


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    text: str


@dataclass(frozen=True)
class PrincipalToken:
    user_id: str
    org_id: str
    email: str
    subject: str
    roles: frozenset[str]
    access_token: str


@dataclass(frozen=True)
class TenantWorld:
    org_id: str
    marker: str
    document_id: str
    ticket_id: str
    run_id: str
    approval_id: str


class Phase4Client:
    def __init__(self, base_url: str, token_path: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_path = token_path

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, object] | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20,
    ) -> ApiResponse:
        request_headers = dict(headers or {})
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif content_type:
            request_headers["Content-Type"] = content_type

        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code

        text = raw.decode("utf-8", errors="replace")
        try:
            body = json.loads(text) if text else None
        except json.JSONDecodeError:
            body = None
        return ApiResponse(status=status, body=body, text=text)

    def issue_token(
        self,
        *,
        email: str,
        subject: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Use the D18 local issuer; validation remains the shipping JWT path.

        The path is configurable because the spec defines the helper contract,
        not a product route name. The default is the conventional dev route
        established for this repository's local issuer.
        """
        response = self.request(
            "POST",
            self.token_path,
            json_body={
                "email": email,
                "subject": subject,
                "expires_in_seconds": expires_in_seconds,
            },
        )
        assert response.status in {200, 201}, (
            "Phase 4 gates require the local dev issuer from D18; set "
            f"PHASE4_TOKEN_PATH if its route differs. {response_detail(response)}"
        )
        assert isinstance(response.body, dict), response_detail(response)
        token = response.body.get("access_token", response.body.get("token"))
        assert (
            isinstance(token, str) and token
        ), f"local issuer response lacks access_token: {response.body!r}"
        return token

    def upload_bytes(
        self,
        token: str | None,
        *,
        filename: str,
        title: str,
        content: bytes,
    ) -> ApiResponse:
        boundary = f"flowforge-phase4-{uuid4().hex}"
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="title"\r\n\r\n',
            title.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            ('Content-Disposition: form-data; name="file"; ' f'filename="{filename}"\r\n').encode(),
            f"Content-Type: {media_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self.request(
            "POST",
            "/api/documents",
            token=token,
            data=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=30,
        )

    def create_ticket(
        self,
        token: str,
        *,
        title: str,
        description: str,
        priority: str = "P4",
        extra: dict[str, object] | None = None,
    ) -> ApiResponse:
        payload: dict[str, object] = {
            "title": title,
            "description": description,
            "department": "Information Technology",
            "service": "MeridianConnect VPN",
            "priority": priority,
        }
        payload.update(extra or {})
        return self.request("POST", "/api/tickets", token=token, json_body=payload)

    def start_run(self, token: str, ticket_id: str) -> ApiResponse:
        return self.request(
            "POST",
            "/api/runs",
            token=token,
            json_body={"ticket_id": ticket_id},
        )


def response_detail(response: ApiResponse) -> str:
    return f"HTTP {response.status}: {response.text[:1500]}"


def object_body(response: ApiResponse, *wrappers: str) -> dict[str, object]:
    assert isinstance(response.body, dict), response_detail(response)
    for wrapper in wrappers:
        value = response.body.get(wrapper)
        if isinstance(value, dict):
            return value
    return response.body


def list_body(response: ApiResponse, *wrappers: str) -> list[dict[str, object]]:
    assert response.status == 200, response_detail(response)
    payload = response.body
    if isinstance(payload, dict):
        for wrapper in wrappers:
            if isinstance(payload.get(wrapper), list):
                payload = payload[wrapper]
                break
    assert isinstance(payload, list) and all(
        isinstance(item, dict) for item in payload
    ), f"expected a list response: {response.body!r}"
    return payload


def identifier_from(response: ApiResponse, *wrappers: str) -> str:
    assert response.status in {200, 201, 202}, response_detail(response)
    body = object_body(response, *wrappers)
    value = body.get("id")
    assert isinstance(value, str) and value, f"response lacks id: {response.body!r}"
    return value


def wait_for_run(
    client: Phase4Client,
    *,
    token: str,
    run_id: str,
    statuses: set[str],
    timeout: float | None = None,
) -> dict[str, object]:
    timeout = timeout or float(os.environ.get("PHASE4_RUN_TIMEOUT_SECONDS", "120"))
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.request("GET", f"/api/runs/{run_id}", token=token)
        assert response.status == 200, response_detail(response)
        last = object_body(response, "run")
        status = last.get("status")
        assert isinstance(status, str), last
        if status in statuses:
            return last
        if status in TERMINAL_RUN_STATUSES:
            pytest.fail(
                f"run {run_id} reached unexpected terminal {status!r}; "
                f"expected {sorted(statuses)!r}; run={last!r}"
            )
        time.sleep(0.2)
    pytest.fail(f"run {run_id} did not reach {sorted(statuses)!r}; last={last!r}")


def wait_for_document(
    client: Phase4Client,
    *,
    token: str,
    document_id: str,
    timeout: float = 120,
) -> None:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        response = client.request("GET", f"/api/documents/{document_id}", token=token)
        assert response.status == 200, response_detail(response)
        body = object_body(response, "document")
        last = body
        if body.get("status") == "ready":
            return
        assert body.get("status") != "failed", body
        time.sleep(0.2)
    pytest.fail(f"document {document_id} did not become ready: {last!r}")


def wait_for_approval(
    client: Phase4Client,
    *,
    token: str,
    run_id: str,
    timeout: float | None = None,
) -> dict[str, object]:
    run = wait_for_run(
        client,
        token=token,
        run_id=run_id,
        statuses={"awaiting_approval", "failed"},
        timeout=timeout,
    )
    assert run.get("status") == "awaiting_approval", run
    timeout = timeout or float(os.environ.get("PHASE4_RUN_TIMEOUT_SECONDS", "120"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.request("GET", "/api/approvals?status=pending", token=token)
        for approval in list_body(response, "approvals", "items"):
            if str(approval.get("run_id")) == run_id:
                approval_id = approval.get("id", approval.get("approval_id"))
                assert isinstance(approval_id, str) and approval_id
                detail = client.request("GET", f"/api/approvals/{approval_id}", token=token)
                assert detail.status == 200, response_detail(detail)
                return object_body(detail, "approval")
        time.sleep(0.2)
    pytest.fail(f"run {run_id} has no pending approval")


def create_pending_approval(
    client: Phase4Client,
    *,
    operator_token: str,
    approver_token: str,
    marker: str,
) -> tuple[str, str, dict[str, object]]:
    ticket_response = client.create_ticket(
        operator_token,
        title=f"Phase 4 approval {marker}",
        description=(
            "A remote employee cannot connect to MeridianConnect VPN. Apply the "
            f"documented routing and recovery steps. Marker {marker}."
        ),
    )
    ticket_id = identifier_from(ticket_response, "ticket")
    run_id = identifier_from(client.start_run(operator_token, ticket_id), "run")
    approval = wait_for_approval(client, token=approver_token, run_id=run_id)
    return ticket_id, run_id, approval


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


async def _seed_principals(
    database_url: str,
) -> dict[str, dict[str, tuple[str, str, str, frozenset[str]]]]:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required for Phase 4 gate setup") from exc

    tenants: dict[str, dict[str, tuple[str, str, str, frozenset[str]]]] = {}
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        for tenant_label in ("a", "b"):
            org_id = str(uuid4())
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                UUID(org_id),
                f"Phase 4 Gate Organization {tenant_label.upper()} {org_id[:8]}",
            )
            tenant: dict[str, tuple[str, str, str, frozenset[str]]] = {}
            role_sets = {
                "administrator": frozenset({"administrator"}),
                "operator": frozenset({"operator"}),
                "approver": frozenset({"approver"}),
                "all_roles": frozenset(ROLE_NAMES),
            }
            for principal_label, roles in role_sets.items():
                user_id = str(uuid4())
                subject = f"phase4|{uuid4()}"
                email = f"phase4-{tenant_label}-{principal_label}-{user_id[:8]}@example.test"
                await connection.execute(
                    """
                    INSERT INTO users (id, org_id, email, auth_subject)
                    VALUES ($1, $2, $3, NULL)
                    """,
                    UUID(user_id),
                    UUID(org_id),
                    email,
                )
                for role in roles:
                    await connection.execute(
                        "INSERT INTO user_roles (user_id, role) VALUES ($1, $2)",
                        UUID(user_id),
                        role,
                    )
                tenant[principal_label] = (user_id, subject, email, roles)
            tenant["_org"] = (org_id, "", "", frozenset())
            tenants[tenant_label] = tenant
    finally:
        await connection.close()
    return tenants


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def phase4_client() -> Phase4Client:
    base_url = os.environ.get("PHASE4_BASE_URL", DEFAULT_BASE_URL)
    client = Phase4Client(
        base_url,
        os.environ.get("PHASE4_TOKEN_PATH", DEFAULT_TOKEN_PATH),
    )
    try:
        health = client.request("GET", "/api/health", timeout=2)
    except (TimeoutError, URLError, OSError) as exc:
        message = f"Phase 4 stack is not reachable at {base_url}: {exc}"
        if _truthy("PHASE4_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    if health.status != 200:
        message = f"Phase 4 health check failed: {response_detail(health)}"
        if _truthy("PHASE4_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    return client


@pytest.fixture(scope="session")
def phase4_database_url() -> str:
    value = os.environ.get("PHASE4_DATABASE_URL")
    if not value:
        message = "PHASE4_DATABASE_URL is required for isolated gate setup"
        if _truthy("PHASE4_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    return value


@pytest.fixture(scope="session")
def phase4_principals(
    phase4_client: Phase4Client,
    phase4_database_url: str,
) -> dict[str, dict[str, PrincipalToken]]:
    try:
        seeded = asyncio.run(_seed_principals(phase4_database_url))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"could not seed Phase 4 gate principals: {exc}")

    result: dict[str, dict[str, PrincipalToken]] = {}
    for tenant_label, principals in seeded.items():
        org_id = principals["_org"][0]
        result[tenant_label] = {}
        for label, (user_id, subject, email, roles) in principals.items():
            if label == "_org":
                continue
            token = phase4_client.issue_token(email=email, subject=subject)
            me = phase4_client.request("GET", "/api/me", token=token)
            assert me.status == 200, (
                "first-login provisioning must link a seeded email to its subject: "
                f"{response_detail(me)}"
            )
            result[tenant_label][label] = PrincipalToken(
                user_id=user_id,
                org_id=org_id,
                email=email,
                subject=subject,
                roles=roles,
                access_token=token,
            )
    return result


@pytest.fixture(scope="session")
def phase4_world(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> dict[str, TenantWorld]:
    worlds: dict[str, TenantWorld] = {}
    for tenant_label in ("a", "b"):
        principals = phase4_principals[tenant_label]
        admin = principals["administrator"].access_token
        operator = principals["operator"].access_token
        approver = principals["approver"].access_token
        marker = f"phase4-tenant-{tenant_label}-{uuid4().hex}"
        document = phase4_client.upload_bytes(
            admin,
            filename=f"{marker}.md",
            title=f"Phase 4 tenant {tenant_label.upper()} policy {marker}",
            content=(
                f"# {marker}\n\nMeridianConnect VPN incidents for {marker} are routed "
                "to IT Infrastructure. Verify network access, retry MFA, and add "
                "an internal recovery note."
            ).encode(),
        )
        document_id = identifier_from(document, "document")
        wait_for_document(phase4_client, token=admin, document_id=document_id)
        ticket_id, run_id, approval = create_pending_approval(
            phase4_client,
            operator_token=operator,
            approver_token=approver,
            marker=marker,
        )
        approval_id = approval.get("id", approval.get("approval_id"))
        assert isinstance(approval_id, str) and approval_id
        worlds[tenant_label] = TenantWorld(
            org_id=principals["operator"].org_id,
            marker=marker,
            document_id=document_id,
            ticket_id=ticket_id,
            run_id=run_id,
            approval_id=approval_id,
        )
    return worlds
