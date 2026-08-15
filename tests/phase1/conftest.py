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


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    text: str


class Phase1Client:
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

    def upload_bytes(
        self,
        *,
        org_id: str,
        filename: str,
        content: bytes,
        title: str,
        version: str = "1.0",
    ) -> ApiResponse:
        boundary = f"flowforge-phase1-{uuid4().hex}"
        fields = {
            "org_id": org_id,
            "title": title,
            "version": version,
        }
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode(),
                    value.encode(),
                    b"\r\n",
                ]
            )
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.extend(
            [
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
        )
        return self.request(
            "POST",
            "/api/documents",
            org_id=org_id,
            data=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=30,
        )

    def upload_path(
        self,
        *,
        org_id: str,
        path: Path,
        title: str,
        version: str = "1.0",
    ) -> ApiResponse:
        return self.upload_bytes(
            org_id=org_id,
            filename=path.name,
            content=path.read_bytes(),
            title=title,
            version=version,
        )

    def document_status(self, org_id: str, document_id: str) -> ApiResponse:
        return self.request(
            "GET",
            f"/api/documents/{document_id}",
            org_id=org_id,
        )

    def list_documents(self, org_id: str) -> ApiResponse:
        return self.request("GET", "/api/documents", org_id=org_id)

    def retrieve(self, org_id: str, query: str, k: int) -> ApiResponse:
        return self.request(
            "POST",
            "/api/retrieve",
            org_id=org_id,
            json_body={"query": query, "k": k},
            timeout=30,
        )

    def reingest(self, org_id: str, document_id: str) -> ApiResponse:
        return self.request(
            "POST",
            f"/api/documents/{document_id}/reingest",
            org_id=org_id,
            json_body={},
        )


def response_detail(response: ApiResponse) -> str:
    return f"HTTP {response.status}: {response.text[:1000]}"


def document_id_from(response: ApiResponse) -> str:
    assert isinstance(response.body, dict), response_detail(response)
    document_id = response.body.get("id", response.body.get("document_id"))
    assert isinstance(document_id, str) and document_id, (
        f"202 upload response must include a document id: {response.body!r}"
    )
    return document_id


def documents_from(response: ApiResponse) -> list[dict[str, object]]:
    assert response.status == 200, response_detail(response)
    payload = response.body
    if isinstance(payload, dict):
        payload = payload.get("documents")
    assert isinstance(payload, list), (
        f"document list must be a list or {{'documents': [...]}}: {response.body!r}"
    )
    assert all(isinstance(item, dict) for item in payload)
    return payload


def retrieval_results_from(response: ApiResponse) -> list[dict[str, object]]:
    assert response.status == 200, response_detail(response)
    payload = response.body
    if isinstance(payload, dict):
        payload = payload.get("results")
    assert isinstance(payload, list), (
        f"retrieval response must be a list or {{'results': [...]}}: {response.body!r}"
    )
    assert all(isinstance(item, dict) for item in payload)
    return payload


def wait_for_document_status(
    client: Phase1Client,
    *,
    org_id: str,
    document_id: str,
    terminal_statuses: set[str],
    timeout: float,
    interval: float = 0.2,
) -> tuple[dict[str, object], float]:
    started = time.monotonic()
    last_response: ApiResponse | None = None
    while time.monotonic() - started < timeout:
        last_response = client.document_status(org_id, document_id)
        assert last_response.status == 200, response_detail(last_response)
        assert isinstance(last_response.body, dict), response_detail(last_response)
        status = last_response.body.get("status")
        assert isinstance(status, str), (
            f"status response must include string status: {last_response.body!r}"
        )
        if status in terminal_statuses:
            return last_response.body, time.monotonic() - started
        time.sleep(interval)
    pytest.fail(
        f"document {document_id} did not reach {sorted(terminal_statuses)} "
        f"within {timeout:.0f}s; last response={last_response!r}"
    )


def _truthy_environment(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    scheme = "postgresql"
    return urlunsplit(
        (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


async def _seed_organizations(database_url: str, org_ids: tuple[str, ...]) -> None:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError(
            "asyncpg is required to seed the two Phase 1 gate organizations"
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
                f"Phase 1 Gate Organization {index} {org_id[:8]}",
            )
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def phase1_client() -> Phase1Client:
    base_url = os.environ.get("PHASE1_BASE_URL", DEFAULT_BASE_URL)
    client = Phase1Client(
        base_url=base_url,
        org_header=os.environ.get("PHASE1_ORG_HEADER", DEFAULT_ORG_HEADER),
    )
    try:
        response = client.request("GET", "/api/health", timeout=2)
    except (TimeoutError, URLError, OSError) as exc:
        message = f"Phase 1 stack is not reachable at {base_url}: {exc}"
        if _truthy_environment("PHASE1_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    if response.status != 200:
        message = f"Phase 1 stack health check failed: {response_detail(response)}"
        if _truthy_environment("PHASE1_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)
    return client


@pytest.fixture(scope="session")
def organization_ids() -> tuple[str, str]:
    configured = (
        os.environ.get("PHASE1_ORG_A_ID"),
        os.environ.get("PHASE1_ORG_B_ID"),
    )
    if all(configured):
        org_ids = (str(configured[0]), str(configured[1]))
    elif any(configured):
        pytest.fail("set both PHASE1_ORG_A_ID and PHASE1_ORG_B_ID, or neither")
    else:
        org_ids = (str(uuid4()), str(uuid4()))
        database_url = os.environ.get("PHASE1_DATABASE_URL")
        if not database_url:
            message = (
                "PHASE1_DATABASE_URL is required to create isolated gate organizations; "
                "alternatively set PHASE1_ORG_A_ID and PHASE1_ORG_B_ID"
            )
            if _truthy_environment("PHASE1_REQUIRE_LIVE"):
                pytest.fail(message)
            pytest.skip(message)
        try:
            asyncio.run(_seed_organizations(database_url, org_ids))
        except Exception as exc:  # noqa: BLE001 - preserve integration setup failure
            pytest.fail(f"could not seed Phase 1 gate organizations: {exc}")

    assert org_ids[0] != org_ids[1], "tenant isolation requires two distinct org ids"
    for org_id in org_ids:
        UUID(org_id)
    return org_ids


@pytest.fixture(scope="session")
def org_a_id(organization_ids: tuple[str, str]) -> str:
    return organization_ids[0]


@pytest.fixture(scope="session")
def org_b_id(organization_ids: tuple[str, str]) -> str:
    return organization_ids[1]


@pytest.fixture(scope="session")
def worker_recovery_org_id() -> str:
    database_url = os.environ.get("PHASE1_DATABASE_URL")
    if not database_url:
        message = (
            "PHASE1_DATABASE_URL is required to create the isolated worker-recovery "
            "organization"
        )
        if _truthy_environment("PHASE1_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)

    org_id = str(uuid4())
    try:
        asyncio.run(_seed_organizations(database_url, (org_id,)))
    except Exception as exc:  # noqa: BLE001 - preserve integration setup failure
        pytest.fail(f"could not seed the isolated worker-recovery organization: {exc}")
    return org_id


@pytest.fixture(scope="session")
def tenant_probe_organization_ids() -> tuple[str, str]:
    database_url = os.environ.get("PHASE1_DATABASE_URL")
    if not database_url:
        message = (
            "PHASE1_DATABASE_URL is required to create isolated tenant-probe "
            "organizations"
        )
        if _truthy_environment("PHASE1_REQUIRE_LIVE"):
            pytest.fail(message)
        pytest.skip(message)

    org_ids = (str(uuid4()), str(uuid4()))
    try:
        asyncio.run(_seed_organizations(database_url, org_ids))
    except Exception as exc:  # noqa: BLE001 - preserve integration setup failure
        pytest.fail(f"could not seed isolated tenant-probe organizations: {exc}")
    return org_ids


def locate_corpus_paths(repository_root: Path) -> tuple[dict[str, Path], list[str]]:
    enterprise_dir = repository_root / "fixtures" / "enterprise"
    required_extensions = {
        "MD-IT-001": ".pdf",
        "MD-IT-002": ".pdf",
        "MD-IT-003": ".md",
        "MD-IT-004": ".md",
        "MD-IT-005": ".md",
        "MD-IT-006": ".md",
        "MD-IT-007": ".md",
        "MD-IT-008": ".pdf",
        "MD-IT-009": ".txt",
        "MD-IT-010": ".md",
    }
    found: dict[str, Path] = {}
    missing: list[str] = []
    for doc_id, extension in required_extensions.items():
        matches = sorted(
            path
            for path in enterprise_dir.rglob(f"*{extension}")
            if doc_id in path.stem.upper()
        )
        if len(matches) != 1:
            missing.append(
                f"{doc_id} ({extension}, found {len(matches)} matching files)"
            )
        else:
            found[doc_id] = matches[0]
    return found, missing


# The human-readable title each corpus doc is uploaded under. The upload title
# is f"{doc_id} — {CORPUS_TITLES[doc_id]}", so retrieval's document_title carries
# both the id and these distinctive words — the metadata gate queries by title
# because a bare doc-id string ("002") also appears in other docs' cross-references
# and cannot reliably surface its own doc.
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


@pytest.fixture(scope="session")
def corpus_paths(repository_root: Path) -> dict[str, Path]:
    found, missing = locate_corpus_paths(repository_root)
    assert not missing, (
        "G1.1 requires the ten approved Meridian corpus fixtures: " + "; ".join(missing)
    )
    return found


@pytest.fixture(scope="session")
def corpus_titles() -> dict[str, str]:
    return dict(CORPUS_TITLES)


@pytest.fixture(scope="session")
def ingested_corpus(
    phase1_client: Phase1Client,
    org_a_id: str,
    corpus_paths: dict[str, Path],
) -> dict[str, str]:
    document_ids: dict[str, str] = {}
    for doc_id, path in corpus_paths.items():
        response = phase1_client.upload_path(
            org_id=org_a_id,
            path=path,
            title=f"{doc_id} — {CORPUS_TITLES[doc_id]}",
        )
        assert response.status == 202, response_detail(response)
        document_ids[doc_id] = document_id_from(response)

    for doc_id, document_id in document_ids.items():
        status, _ = wait_for_document_status(
            phase1_client,
            org_id=org_a_id,
            document_id=document_id,
            terminal_statuses={"ready", "failed"},
            timeout=float(os.environ.get("PHASE1_INGEST_TIMEOUT_SECONDS", "120")),
        )
        assert status["status"] == "ready", (
            f"{doc_id} ingestion did not succeed: {status!r}"
        )
    return document_ids


@pytest.fixture
def ensure_worker_running(repository_root: Path) -> Iterator[None]:
    yield
    if not _truthy_environment("PHASE1_MANAGE_WORKER"):
        return
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        return
    compose_file = os.environ.get(
        "PHASE1_COMPOSE_FILE",
        str(repository_root / "infra" / "docker-compose.yml"),
    )
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d", "worker"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
