from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest

from tests.support.auth import gate_database_url, token_for_org

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_ORG_HEADER = "X-Org-ID"
# Statuses at which *triage* has finished and a Phase 2 gate may inspect the run.
#
# `awaiting_approval` is settled from Phase 2's point of view: spec 04 §4 ends
# triage at the durable pause, so a run resting there has produced its full
# structured output, evidence and audit trail — everything G2.1-G2.6 assert on.
# It is not a terminal *run* status (Phase 3 resumes it), which is why the name
# says "settled for triage" rather than "terminal".
#
# Without it, every Phase 2 gate that waits for a run times out once Phase 3
# lands, and the failure looks like a triage regression rather than the
# intended new pause.
TERMINAL_RUN_STATUSES = {"completed", "rejected", "failed", "awaiting_approval"}
# Statuses meaning "triage produced a valid result". From Phase 3 a successful
# triage rests at `awaiting_approval` rather than `completed` — the run is not
# finished, but everything Phase 2 gates on (structured output, evidence,
# citations, audit trail) is present and final. `failed` is still a failure.
TRIAGE_SUCCESS_STATUSES = {"completed", "awaiting_approval"}
READ_TOOL_NAMES = {"get_ticket", "search_company_knowledge"}


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    text: str


class Phase2Client:
    def __init__(self, base_url: str, org_header: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.org_header = org_header

    def request(
        self,
        method: str,
        path: str,
        *,
        org_id: str | None = None,
        json_body: dict[str, object] | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 10,
    ) -> ApiResponse:
        headers: dict[str, str] = {}
        if org_id:
            headers[self.org_header] = org_id
            # Phase 4: org_id now comes from the authenticated principal, so
            # the header above no longer selects a tenant. It is left in place
            # deliberately -- G4.5 proves it is ignored rather than honoured.
            headers["Authorization"] = "Bearer " + token_for_org(
                self.base_url, gate_database_url(), org_id
            )
            separator = "&" if "?" in path else "?"
            path = f"{path}{separator}{urlencode({'org_id': org_id})}"
        if json_body is not None:
            payload = dict(json_body)
            if org_id:
                payload.setdefault("org_id", org_id)
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
        department: str = "Information Technology",
        service: str = "Service Desk",
        priority: str = "P3",
    ) -> ApiResponse:
        return self.request(
            "POST",
            "/api/tickets",
            org_id=org_id,
            json_body={
                "title": title,
                "description": description,
                "department": department,
                "service": service,
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

    def retrieve(self, org_id: str, query: str, k: int = 20) -> ApiResponse:
        return self.request(
            "POST",
            "/api/retrieve",
            org_id=org_id,
            json_body={"query": query, "k": k},
            timeout=30,
        )

    def upload_path(self, org_id: str, path: Path, title: str) -> ApiResponse:
        boundary = f"flowforge-phase2-{uuid4().hex}"
        fields = {"org_id": org_id, "title": title, "version": "1.0"}
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode(),
                    b"\r\n",
                ]
            )
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="file"; '
                    f'filename="{path.name}"\r\n'
                ).encode(),
                f"Content-Type: {media_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
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


def response_detail(response: ApiResponse) -> str:
    return f"HTTP {response.status}: {response.text[:1000]}"


def _object_body(
    response: ApiResponse, wrapper: str | None = None
) -> dict[str, object]:
    assert isinstance(response.body, dict), response_detail(response)
    body = response.body
    if wrapper and isinstance(body.get(wrapper), dict):
        body = body[wrapper]
    return body


def ticket_id_from(response: ApiResponse) -> str:
    assert response.status in {200, 201}, response_detail(response)
    body = _object_body(response, "ticket")
    ticket_id = body.get("id", body.get("ticket_id"))
    assert isinstance(ticket_id, str) and ticket_id, (
        f"ticket creation response must include an id: {response.body!r}"
    )
    return ticket_id


def run_id_from(response: ApiResponse) -> str:
    assert response.status in {200, 202}, response_detail(response)
    body = _object_body(response, "run")
    run_id = body.get("id", body.get("run_id"))
    assert isinstance(run_id, str) and run_id, (
        f"triage response must include a run id: {response.body!r}"
    )
    return run_id


def document_id_from(response: ApiResponse) -> str:
    assert response.status == 202, response_detail(response)
    body = _object_body(response, "document")
    document_id = body.get("id", body.get("document_id"))
    assert isinstance(document_id, str) and document_id
    return document_id


def run_detail_from(response: ApiResponse) -> dict[str, object]:
    assert response.status == 200, response_detail(response)
    return _object_body(response, "run")


def audit_entries_from(run: dict[str, object]) -> list[dict[str, object]]:
    entries = run.get("audit_entries", run.get("audit_log"))
    assert isinstance(entries, list), (
        f"GET /api/runs/{{id}} must return audit_entries for G2.5: {run!r}"
    )
    assert all(isinstance(entry, dict) for entry in entries)
    return entries


def evidence_from(run: dict[str, object]) -> list[dict[str, object]]:
    evidence = run.get("evidence", run.get("evidence_used"))
    assert isinstance(evidence, list), (
        f"GET /api/runs/{{id}} must return evidence used: {run!r}"
    )
    assert all(isinstance(item, dict) for item in evidence)
    return evidence


def operation_name(entry: dict[str, object]) -> str:
    name = entry.get("tool", entry.get("name"))
    assert isinstance(name, str) and name.strip(), (
        f"audit entry lacks tool name: {entry!r}"
    )
    return name


def llm_audit_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    return [entry for entry in entries if operation_name(entry) not in READ_TOOL_NAMES]


def assert_failure_reason(run: dict[str, object], expected: str) -> None:
    # The typed reason is its own field; `error` carries the human-readable
    # detail and is only consulted when a run reports no typed reason at all.
    error = run.get("failure_reason") or run.get("error")
    if isinstance(error, dict):
        error = error.get("reason", error.get("code", error.get("message")))
    assert isinstance(error, str) and expected in error.lower(), (
        f"expected typed failure reason {expected!r}, got {run!r}"
    )


def wait_for_run(
    client: Phase2Client,
    *,
    org_id: str,
    run_id: str,
    timeout: float | None = None,
) -> dict[str, object]:
    timeout = timeout or float(os.environ.get("PHASE2_RUN_TIMEOUT_SECONDS", "90"))
    started = time.monotonic()
    last_run: dict[str, object] | None = None
    while time.monotonic() - started < timeout:
        last_run = run_detail_from(client.get_run(org_id, run_id))
        status = last_run.get("status")
        assert isinstance(status, str), f"run detail lacks status: {last_run!r}"
        if status in TERMINAL_RUN_STATUSES:
            return last_run
        time.sleep(0.2)
    pytest.fail(
        f"run {run_id} did not reach {sorted(TERMINAL_RUN_STATUSES)} "
        f"within {timeout:.0f}s; last run={last_run!r}"
    )


def triage_and_wait(
    client: Phase2Client,
    *,
    org_id: str,
    title: str,
    description: str,
    department: str = "Information Technology",
    service: str = "Service Desk",
    priority: str = "P3",
) -> tuple[str, dict[str, object]]:
    ticket = client.create_ticket(
        org_id,
        title=title,
        description=description,
        department=department,
        service=service,
        priority=priority,
    )
    ticket_id = ticket_id_from(ticket)
    run_id = run_id_from(client.triage(org_id, ticket_id))
    return ticket_id, wait_for_run(client, org_id=org_id, run_id=run_id)


def fake_completion_directive(mode: str, *, field: str | None = None) -> str:
    """Black-box fault injection required by Phase 2 key decision 3."""
    suffix = f":{field}" if field else ""
    return f"[[FLOWFORGE_FAKE_COMPLETION:{mode}{suffix}]]"


def _truthy_environment(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(
        ("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


async def _seed_organizations(database_url: str, org_ids: tuple[str, ...]) -> None:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError(
            "asyncpg is required to seed Phase 2 gate organizations"
        ) from exc

    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        for index, org_id in enumerate(org_ids, start=1):
            await connection.execute(
                """
                INSERT INTO organizations (id, name)
                VALUES ($1, $2)
                ON CONFLICT (id) DO NOTHING
                """,
                UUID(org_id),
                f"Phase 2 Gate Organization {index} {org_id[:8]}",
            )
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def phase2_client() -> Phase2Client:
    base_url = os.environ.get("PHASE2_BASE_URL", DEFAULT_BASE_URL)
    client = Phase2Client(
        base_url=base_url,
        org_header=os.environ.get("PHASE2_ORG_HEADER", DEFAULT_ORG_HEADER),
    )
    try:
        response = client.request("GET", "/api/health", timeout=2)
    except (TimeoutError, URLError, OSError) as exc:
        message = f"Phase 2 stack is not reachable at {base_url}: {exc}"
        if _truthy_environment("PHASE2_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    if response.status != 200:
        message = f"Phase 2 stack health check failed: {response_detail(response)}"
        if _truthy_environment("PHASE2_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    return client


@pytest.fixture(scope="session")
def phase2_organization_ids() -> tuple[str, str, str, str]:
    environment_names = (
        "PHASE2_CORPUS_ORG_ID",
        "PHASE2_EMPTY_ORG_ID",
        "PHASE2_ORG_A_ID",
        "PHASE2_ORG_B_ID",
    )
    configured = tuple(os.environ.get(name) for name in environment_names)
    if all(configured):
        org_ids = tuple(str(org_id) for org_id in configured)
    elif any(configured):
        pytest.fail(f"set all of {environment_names!r}, or none")
    else:
        org_ids = tuple(str(uuid4()) for _ in environment_names)
        database_url = os.environ.get("PHASE2_DATABASE_URL")
        if not database_url:
            message = (
                "PHASE2_DATABASE_URL is required to create isolated gate organizations; "
                f"alternatively set all of {environment_names!r}"
            )
            if _truthy_environment("PHASE2_REQUIRE_LIVE"):
                pytest.fail(message)
            pytest.skip(message)
        try:
            asyncio.run(_seed_organizations(database_url, org_ids))
        except Exception as exc:  # noqa: BLE001 - preserve integration setup failure
            pytest.fail(f"could not seed Phase 2 gate organizations: {exc}")

    assert len(set(org_ids)) == len(org_ids), "Phase 2 gates require four distinct orgs"
    for org_id in org_ids:
        UUID(org_id)
    return org_ids  # type: ignore[return-value]


@pytest.fixture(scope="session")
def corpus_org_id(phase2_organization_ids: tuple[str, str, str, str]) -> str:
    return phase2_organization_ids[0]


@pytest.fixture(scope="session")
def empty_org_id(phase2_organization_ids: tuple[str, str, str, str]) -> str:
    return phase2_organization_ids[1]


@pytest.fixture(scope="session")
def isolation_org_ids(
    phase2_organization_ids: tuple[str, str, str, str],
) -> tuple[str, str]:
    return phase2_organization_ids[2], phase2_organization_ids[3]


CORPUS_TITLES = {
    "MD-IT-001": "VPN Access Policy",
    "MD-IT-002": "Incident Priority & Escalation Guidelines",
    "MD-IT-003": "Password Reset & Account Lockout Procedure",
    "MD-IT-004": "MFA Enrollment & Recovery",
    "MD-IT-005": "Hardware Request & Replacement Policy",
    "MD-IT-006": "Software & SaaS License Request Procedure",
    "MD-IT-007": "Email & Collaboration Troubleshooting Guide",
    "MD-IT-008": "Security Incident Reporting Policy",
    "MD-IT-009": "Onboarding & Offboarding IT Checklist",
    "MD-IT-010": "Remote Work IT Standards",
}


def locate_corpus_paths(repository_root: Path) -> dict[str, Path]:
    enterprise_dir = repository_root / "fixtures" / "enterprise"
    paths: dict[str, Path] = {}
    for doc_id in CORPUS_TITLES:
        matches = sorted(
            path for path in enterprise_dir.iterdir() if doc_id in path.stem.upper()
        )
        assert len(matches) == 1, (
            f"expected one fixture for {doc_id}, found {matches!r}"
        )
        paths[doc_id] = matches[0]
    return paths


def wait_for_document_ready(
    client: Phase2Client,
    *,
    org_id: str,
    document_id: str,
    timeout: float = 120,
) -> None:
    started = time.monotonic()
    last: dict[str, object] | None = None
    while time.monotonic() - started < timeout:
        response = client.get_document(org_id, document_id)
        assert response.status == 200, response_detail(response)
        last = _object_body(response, "document")
        status = last.get("status")
        if status == "ready":
            return
        assert status != "failed", f"document ingestion failed: {last!r}"
        time.sleep(0.2)
    pytest.fail(f"document {document_id} did not become ready: {last!r}")


@pytest.fixture(scope="session")
def ingested_phase2_corpus(
    repository_root: Path,
    phase2_client: Phase2Client,
    corpus_org_id: str,
) -> dict[str, str]:
    uploaded: dict[str, str] = {}
    for doc_id, path in locate_corpus_paths(repository_root).items():
        response = phase2_client.upload_path(
            corpus_org_id,
            path,
            f"{doc_id} — {CORPUS_TITLES[doc_id]}",
        )
        uploaded[doc_id] = document_id_from(response)
    for document_id in uploaded.values():
        wait_for_document_ready(
            phase2_client,
            org_id=corpus_org_id,
            document_id=document_id,
        )
    return uploaded


@pytest.fixture
def corpus_ready(ingested_phase2_corpus: dict[str, str]) -> Iterator[None]:
    assert ingested_phase2_corpus
    yield
