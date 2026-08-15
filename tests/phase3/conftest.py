from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_ORG_HEADER = "X-Org-ID"
DEFAULT_USER_HEADER = "X-User-ID"
TERMINAL_RUN_STATUSES = {"completed", "rejected", "failed"}
WRITE_OPERATION_ALIASES = {
    "assign_ticket": "assign_ticket",
    "change_priority": "change_ticket_priority",
    "change_ticket_priority": "change_ticket_priority",
    "add_note": "add_internal_note",
    "add_internal_note": "add_internal_note",
}


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    text: str


class Phase3Client:
    def __init__(self, base_url: str, org_header: str, user_header: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.org_header = org_header
        self.user_header = user_header

    def request(
        self,
        method: str,
        path: str,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
        json_body: dict[str, object] | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 15,
    ) -> ApiResponse:
        headers: dict[str, str] = {}
        if org_id:
            headers[self.org_header] = org_id
            separator = "&" if "?" in path else "?"
            path = f"{path}{separator}{urlencode({'org_id': org_id})}"
        if user_id:
            headers[self.user_header] = user_id
        if json_body is not None:
            payload = dict(json_body)
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type

        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
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

    def create_ticket(
        self,
        org_id: str,
        *,
        title: str,
        description: str,
        priority: str = "P4",
    ) -> ApiResponse:
        return self.request(
            "POST",
            "/api/tickets",
            org_id=org_id,
            json_body={
                "title": title,
                "description": description,
                "department": "Information Technology",
                "service": "MeridianConnect VPN",
                "priority": priority,
            },
        )

    def get_ticket(self, org_id: str, ticket_id: str) -> ApiResponse:
        return self.request("GET", f"/api/tickets/{ticket_id}", org_id=org_id)

    def triage(self, org_id: str, ticket_id: str) -> ApiResponse:
        return self.request(
            "POST",
            f"/api/tickets/{ticket_id}/triage",
            org_id=org_id,
            json_body={},
        )

    def get_run(self, org_id: str, run_id: str) -> ApiResponse:
        return self.request("GET", f"/api/runs/{run_id}", org_id=org_id)

    def list_approvals(self, org_id: str, *, status: str = "pending") -> ApiResponse:
        return self.request(
            "GET",
            f"/api/approvals?{urlencode({'status': status})}",
            org_id=org_id,
        )

    def get_approval(self, org_id: str, approval_id: str) -> ApiResponse:
        return self.request("GET", f"/api/approvals/{approval_id}", org_id=org_id)

    def decide(
        self,
        org_id: str,
        user_id: str,
        approval_id: str,
        *,
        decision: str,
        final_values: object | None = None,
        feedback: str | None = None,
    ) -> ApiResponse:
        payload: dict[str, object] = {"decision": decision}
        if final_values is not None:
            payload["final_values"] = final_values
        if feedback is not None:
            payload["feedback"] = feedback
        return self.request(
            "POST",
            f"/api/approvals/{approval_id}/decision",
            org_id=org_id,
            user_id=user_id,
            json_body=payload,
            timeout=30,
        )

    def upload_bytes(
        self,
        org_id: str,
        *,
        filename: str,
        title: str,
        content: bytes,
    ) -> ApiResponse:
        boundary = f"flowforge-phase3-{uuid4().hex}"
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="title"\r\n\r\n',
            title.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            f"Content-Type: {media_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self.request(
            "POST",
            "/api/documents",
            org_id=org_id,
            data=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=30,
        )

    def get_document(self, org_id: str, document_id: str) -> ApiResponse:
        return self.request("GET", f"/api/documents/{document_id}", org_id=org_id)


class MockAdapterControl:
    """Dev-only access to the mock adapter's recorder and failure flag.

    The spec requires both controls but deliberately does not make them product
    APIs. Paths are configurable so the implementation may expose equivalent
    test hooks without coupling these gates to an adapter class.
    """

    def __init__(self, client: Phase3Client, org_id: str) -> None:
        self.client = client
        self.org_id = org_id
        self.recorder_path = os.environ.get(
            "PHASE3_RECORDER_PATH", "/api/test/mock-ticket-system/calls"
        )
        self.failure_path = os.environ.get(
            "PHASE3_FAILURE_PATH", "/api/test/mock-ticket-system/failures"
        )

    def calls(self, run_id: str) -> list[dict[str, object]]:
        separator = "&" if "?" in self.recorder_path else "?"
        response = self.client.request(
            "GET",
            f"{self.recorder_path}{separator}{urlencode({'run_id': run_id})}",
            org_id=self.org_id,
        )
        assert response.status == 200, (
            "G3 gates require the mock adapter call recorder; set "
            f"PHASE3_RECORDER_PATH if its test hook differs. {response_detail(response)}"
        )
        payload = response.body
        if isinstance(payload, dict):
            payload = payload.get("calls", payload.get("items"))
        assert isinstance(payload, list) and all(
            isinstance(item, dict) for item in payload
        ), f"mock adapter recorder must return a call list: {response.body!r}"
        write_calls = []
        for item in payload:
            operation = item.get(
                "tool",
                item.get("operation", item.get("name", item.get("method"))),
            )
            if isinstance(operation, str) and operation in WRITE_OPERATION_ALIASES:
                write_calls.append(item)
        return write_calls

    def inject_timeout(self, failures: int = 10) -> None:
        response = self.client.request(
            "POST",
            self.failure_path,
            org_id=self.org_id,
            json_body={"mode": "timeout", "remaining_failures": failures},
        )
        assert response.status in {200, 201, 204}, (
            "G3.6 requires deterministic adapter timeout injection; set "
            f"PHASE3_FAILURE_PATH if its test hook differs. {response_detail(response)}"
        )

    def clear_failure(self) -> None:
        response = self.client.request("DELETE", self.failure_path, org_id=self.org_id)
        assert response.status in {200, 204, 404}, response_detail(response)


def response_detail(response: ApiResponse) -> str:
    return f"HTTP {response.status}: {response.text[:1000]}"


def object_body(response: ApiResponse, *wrappers: str) -> dict[str, object]:
    assert isinstance(response.body, dict), response_detail(response)
    body = response.body
    for wrapper in wrappers:
        if isinstance(body.get(wrapper), dict):
            return body[wrapper]  # type: ignore[return-value]
    return body


def identifier_from(response: ApiResponse, *, kind: str) -> str:
    expected = {"ticket": {200, 201}, "run": {200, 202}, "document": {200, 202}}
    assert response.status in expected[kind], response_detail(response)
    body = object_body(response, kind)
    value = body.get("id", body.get(f"{kind}_id"))
    assert isinstance(value, str) and value, (
        f"{kind} response lacks id: {response.body!r}"
    )
    return value


def run_detail(client: Phase3Client, org_id: str, run_id: str) -> dict[str, object]:
    response = client.get_run(org_id, run_id)
    assert response.status == 200, response_detail(response)
    return object_body(response, "run")


def approval_detail(
    client: Phase3Client, org_id: str, approval_id: str
) -> dict[str, object]:
    response = client.get_approval(org_id, approval_id)
    assert response.status == 200, response_detail(response)
    return object_body(response, "approval")


def approval_items(response: ApiResponse) -> list[dict[str, object]]:
    assert response.status == 200, response_detail(response)
    payload = response.body
    if isinstance(payload, dict):
        payload = payload.get("approvals", payload.get("items"))
    assert isinstance(payload, list) and all(
        isinstance(item, dict) for item in payload
    ), f"approval inbox must return a list: {response.body!r}"
    return payload


def wait_for_run_status(
    client: Phase3Client,
    *,
    org_id: str,
    run_id: str,
    statuses: set[str],
    timeout: float | None = None,
) -> dict[str, object]:
    timeout = timeout or float(os.environ.get("PHASE3_RUN_TIMEOUT_SECONDS", "120"))
    started = time.monotonic()
    last: dict[str, object] | None = None
    while time.monotonic() - started < timeout:
        last = run_detail(client, org_id, run_id)
        status = last.get("status")
        assert isinstance(status, str), f"run detail lacks status: {last!r}"
        if status in statuses:
            return last
        if status in TERMINAL_RUN_STATUSES:
            pytest.fail(
                f"run {run_id} reached unexpected terminal status {status!r}; "
                f"expected one of {sorted(statuses)!r}; run={last!r}"
            )
        time.sleep(0.2)
    pytest.fail(f"run {run_id} did not reach {sorted(statuses)}; last={last!r}")


def wait_for_approval(
    client: Phase3Client,
    *,
    org_id: str,
    run_id: str,
    timeout: float | None = None,
) -> dict[str, object]:
    run = wait_for_run_status(
        client,
        org_id=org_id,
        run_id=run_id,
        statuses={"awaiting_approval", "failed"},
        timeout=timeout,
    )
    assert run["status"] == "awaiting_approval", (
        f"run failed before creating its durable approval: {run!r}"
    )
    started = time.monotonic()
    timeout = timeout or float(os.environ.get("PHASE3_RUN_TIMEOUT_SECONDS", "120"))
    while time.monotonic() - started < timeout:
        for item in approval_items(client.list_approvals(org_id, status="pending")):
            if str(item.get("run_id")) == run_id:
                approval_id = item.get("id", item.get("approval_id"))
                assert isinstance(approval_id, str) and approval_id
                return approval_detail(client, org_id, approval_id)
        time.sleep(0.2)
    pytest.fail(
        f"run {run_id} reached awaiting_approval without a pending approval row"
    )


def start_pending_run(
    client: Phase3Client,
    *,
    org_id: str,
    marker: str,
    priority: str = "P4",
) -> tuple[str, str, dict[str, object]]:
    ticket = client.create_ticket(
        org_id,
        title=f"VPN approval gate {marker}",
        description=(
            "A remote employee cannot connect to MeridianConnect VPN. Apply the documented "
            f"assignment, priority, and recovery note. Gate marker {marker}."
        ),
        priority=priority,
    )
    ticket_id = identifier_from(ticket, kind="ticket")
    run_id = identifier_from(client.triage(org_id, ticket_id), kind="run")
    approval = wait_for_approval(client, org_id=org_id, run_id=run_id)
    assert approval.get("run_id") == run_id, approval
    return ticket_id, run_id, approval


def wait_for_document_ready(
    client: Phase3Client, *, org_id: str, document_id: str, timeout: float = 120
) -> None:
    started = time.monotonic()
    last: object = None
    while time.monotonic() - started < timeout:
        response = client.get_document(org_id, document_id)
        assert response.status == 200, response_detail(response)
        body = object_body(response, "document")
        last = body
        if body.get("status") == "ready":
            return
        assert body.get("status") != "failed", (
            f"gate evidence ingestion failed: {body!r}"
        )
        time.sleep(0.2)
    pytest.fail(f"gate evidence document did not become ready: {last!r}")


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(
        ("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


async def _seed_gate_principals(
    database_url: str, org_id: str, approver_id: str, second_approver_id: str
) -> None:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required for Phase 3 gate setup") from exc

    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await connection.execute(
            """
            INSERT INTO organizations (id, name)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
            """,
            UUID(org_id),
            f"Phase 3 Gate Organization {org_id[:8]}",
        )
        for index, user_id in enumerate((approver_id, second_approver_id), start=1):
            await connection.execute(
                """
                INSERT INTO users (id, org_id, email)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO NOTHING
                """,
                UUID(user_id),
                UUID(org_id),
                f"phase3-approver-{index}-{user_id[:8]}@example.test",
            )
            await connection.execute(
                """
                INSERT INTO user_roles (user_id, role)
                VALUES ($1, 'approver')
                ON CONFLICT (user_id, role) DO NOTHING
                """,
                UUID(user_id),
            )
    finally:
        await connection.close()


async def _tool_execution_rows(
    database_url: str, run_id: str
) -> list[dict[str, object]]:
    import asyncpg

    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        rows = await connection.fetch(
            """
            SELECT tool, args_hash, result
            FROM tool_executions
            WHERE run_id = $1
            ORDER BY tool, args_hash
            """,
            UUID(run_id),
        )
        return [dict(row) for row in rows]
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def phase3_client() -> Phase3Client:
    base_url = os.environ.get("PHASE3_BASE_URL", DEFAULT_BASE_URL)
    client = Phase3Client(
        base_url,
        os.environ.get("PHASE3_ORG_HEADER", DEFAULT_ORG_HEADER),
        os.environ.get("PHASE3_USER_HEADER", DEFAULT_USER_HEADER),
    )
    try:
        health = client.request("GET", "/api/health", timeout=2)
    except (TimeoutError, URLError, OSError) as exc:
        message = f"Phase 3 stack is not reachable at {base_url}: {exc}"
        if _truthy("PHASE3_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    if health.status != 200:
        message = f"Phase 3 health check failed: {response_detail(health)}"
        if _truthy("PHASE3_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    return client


@pytest.fixture(scope="session")
def phase3_database_url() -> str:
    value = os.environ.get("PHASE3_DATABASE_URL")
    if not value:
        message = "PHASE3_DATABASE_URL is required for isolated gate setup"
        if _truthy("PHASE3_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    return value


@pytest.fixture(scope="session")
def phase3_principals(phase3_database_url: str) -> tuple[str, str, str]:
    configured = (
        os.environ.get("PHASE3_ORG_ID"),
        os.environ.get("PHASE3_APPROVER_USER_ID"),
        os.environ.get("PHASE3_SECOND_APPROVER_USER_ID"),
    )
    if all(configured):
        values = tuple(str(value) for value in configured)
    elif any(configured):
        pytest.fail("set all Phase 3 org/approver ids, or none")
    else:
        values = (str(uuid4()), str(uuid4()), str(uuid4()))
        try:
            asyncio.run(_seed_gate_principals(phase3_database_url, *values))
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"could not seed Phase 3 gate principals: {exc}")
    for value in values:
        UUID(value)
    return values  # type: ignore[return-value]


@pytest.fixture(scope="session")
def phase3_org_id(phase3_principals: tuple[str, str, str]) -> str:
    return phase3_principals[0]


@pytest.fixture(scope="session")
def approver_user_ids(phase3_principals: tuple[str, str, str]) -> tuple[str, str]:
    return phase3_principals[1], phase3_principals[2]


@pytest.fixture(scope="session")
def phase3_evidence_ready(phase3_client: Phase3Client, phase3_org_id: str) -> None:
    content = b"""# MeridianConnect VPN Recovery and Routing

VPN access failures are assigned to IT Infrastructure. A single blocked remote user
should be handled promptly. Add an internal note describing the documented recovery:
verify network access, retry MFA, and escalate persistent connection failures.
"""
    response = phase3_client.upload_bytes(
        phase3_org_id,
        filename="phase3-vpn-policy.md",
        title="Phase 3 VPN Approval Gate Policy",
        content=content,
    )
    document_id = identifier_from(response, kind="document")
    wait_for_document_ready(
        phase3_client, org_id=phase3_org_id, document_id=document_id
    )


@pytest.fixture
def mock_adapter_control(
    phase3_client: Phase3Client, phase3_org_id: str
) -> MockAdapterControl:
    control = MockAdapterControl(phase3_client, phase3_org_id)
    control.clear_failure()
    yield control
    control.clear_failure()


@pytest.fixture
def tool_execution_rows(phase3_database_url: str):
    def load(run_id: str) -> list[dict[str, object]]:
        return asyncio.run(_tool_execution_rows(phase3_database_url, run_id))

    return load


@pytest.fixture
def restart_backend(repository_root: Path, phase3_client: Phase3Client):
    def restart() -> None:
        if not _truthy("PHASE3_MANAGE_BACKEND"):
            pytest.skip("set PHASE3_MANAGE_BACKEND=1 on an isolated stack for G3.1")
        compose_file = os.environ.get(
            "PHASE3_COMPOSE_FILE", str(repository_root / "infra" / "docker-compose.yml")
        )
        command = ["docker", "compose"]
        env_file = os.environ.get("PHASE3_ENV_FILE")
        if env_file:
            command.extend(["--env-file", env_file])
        command.extend(["-f", compose_file, "restart", "backend"])
        result = subprocess.run(
            command,
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                health = phase3_client.request("GET", "/api/health", timeout=2)
            except (TimeoutError, URLError, OSError):
                time.sleep(0.5)
                continue
            if health.status == 200:
                return
            time.sleep(0.5)
        pytest.fail("backend did not become healthy within 60s after restart")

    return restart
