"""Harness for the Phase 5 gates (spec 06, G5.1-G5.5).

Two kinds of gate live here and they need very different things:

* **Pure gates** — determinism, judge schema, config validation, graph shape.
  They import `app/` and touch nothing else, so they run in the fast CI job and
  on a laptop with no stack.
* **Live gates** — metric truth, batch coverage, comparability. They drive the
  real HTTP API against the real worker, because a metric endpoint that has
  never counted a row the pipeline actually wrote is not evidence of anything.

Live gates skip when the stack is absent and **fail** when `PHASE5_REQUIRE_LIVE`
is set, which is how CI stops a silently-skipped gate from being reported as a
pass — the same convention Phases 1-4 use.

Each live gate seeds its own organization. Sharing the demo tenant would make
the metric assertions depend on whatever else has run against that stack, and a
gate whose expected value drifts with unrelated activity is a gate nobody
trusts (G5.3 hand-computes every figure it checks).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
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
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BATCH_TERMINAL = {"completed", "failed"}


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    text: str


@dataclass(frozen=True)
class Tenant:
    """One freshly seeded organization plus a token per role."""

    org_id: str
    tokens: dict[str, str]

    @property
    def admin(self) -> str:
        return self.tokens["administrator"]

    @property
    def operator(self) -> str:
        return self.tokens["operator"]


class Phase5Client:
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
        timeout: float = 30,
    ) -> ApiResponse:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type

        request = Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw, status = response.read(), response.status
        except HTTPError as exc:
            raw, status = exc.read(), exc.code

        text = raw.decode("utf-8", errors="replace")
        try:
            body = json.loads(text) if text else None
        except json.JSONDecodeError:
            body = None
        return ApiResponse(status=status, body=body, text=text)

    def issue_token(self, *, email: str, subject: str) -> str:
        response = self.request(
            "POST", self.token_path, json_body={"email": email, "subject": subject}
        )
        assert response.status in {200, 201}, detail(response)
        assert isinstance(response.body, dict), detail(response)
        token = response.body.get("access_token")
        assert isinstance(token, str) and token, (
            f"dev issuer returned no token: {response.body!r}"
        )
        return token

    def upload_markdown(self, token: str, *, title: str, body: str) -> ApiResponse:
        boundary = f"flowforge-phase5-{uuid4().hex}"
        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="title"\r\n\r\n',
            title.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="file"; '
                f'filename="{title.replace(" ", "-")}.md"\r\n'
            ).encode(),
            b"Content-Type: text/markdown\r\n\r\n",
            body.encode(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self.request(
            "POST",
            "/api/documents",
            token=token,
            data=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
        )


def detail(response: ApiResponse) -> str:
    return f"HTTP {response.status}: {response.text[:1500]}"


def runtime_module(name: str) -> Any:
    """Import a module from `backend/` for the pure gates.

    Same approach as the Phase 2 taxonomy gate: the suite reads the shipping
    code rather than a copy of it, so a gate cannot pass against a
    reimplementation of the thing it is supposed to be guarding.
    """
    backend = str(REPOSITORY_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    return importlib.import_module(name)


def truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(
        ("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


async def connect(database_url: str) -> Any:
    try:
        import asyncpg
    except (
        ImportError
    ) as exc:  # pragma: no cover - environment problem, not a gate failure
        raise RuntimeError("asyncpg is required for the Phase 5 live gates") from exc
    return await asyncpg.connect(asyncpg_url(database_url))


async def _seed_tenant(database_url: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """Create an organization with one user per role.

    One user per role rather than one user holding all three, because G5.3
    asserts that an operator cannot see the cost and accuracy figures (D19
    decision 6) — a combined principal would pass that check for the wrong
    reason.
    """
    org_id = uuid4()
    connection = await connect(database_url)
    users: dict[str, tuple[str, str]] = {}
    try:
        await connection.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, $2)",
            org_id,
            f"Phase 5 Gate Organization {str(org_id)[:8]}",
        )
        for role in ROLE_NAMES:
            user_id = uuid4()
            email = f"phase5-{role}-{str(user_id)[:8]}@gates.test"
            await connection.execute(
                "INSERT INTO users (id, org_id, email, auth_subject) VALUES ($1, $2, $3, NULL)",
                user_id,
                org_id,
                email,
            )
            await connection.execute(
                "INSERT INTO user_roles (user_id, role) VALUES ($1, $2)", user_id, role
            )
            users[role] = (email, f"phase5|{uuid4()}")
    finally:
        await connection.close()
    return str(org_id), users


def new_tenant(client: Phase5Client, database_url: str) -> Tenant:
    org_id, users = asyncio.run(_seed_tenant(database_url))
    tokens = {
        role: client.issue_token(email=email, subject=subject)
        for role, (email, subject) in users.items()
    }
    # First call binds each subject through the ordinary first-login path.
    for role, token in tokens.items():
        me = client.request("GET", "/api/me", token=token)
        assert me.status == 200, (
            f"{role} could not authenticate: {detail(me)}. A 403 here usually "
            f"means PHASE5_DATABASE_URL ({database_url.rsplit('/', 1)[-1]}) is a "
            f"different database from the one {client.base_url} is reading: the "
            "user was seeded somewhere the stack cannot see it."
        )
    return Tenant(org_id=org_id, tokens=tokens)


def eval_fixture() -> dict[str, Any]:
    return json.loads(
        (REPOSITORY_ROOT / "fixtures" / "eval_tickets.json").read_text(encoding="utf-8")
    )


async def _seed_eval_tickets(database_url: str, org_id: str, count: int) -> list[str]:
    """Copy the first `count` fixture tickets into an org, labels omitted.

    Labels stay out of the database exactly as `scripts/load_eval_tickets.py`
    keeps them out: the agent must never be able to read the answer key, and a
    gate that seeded it differently would be testing an easier system than the
    one that ships.
    """
    records = eval_fixture()["eval_tickets"][:count]
    connection = await connect(database_url)
    try:
        for record in records:
            await connection.execute(
                """
                INSERT INTO tickets (
                    id, org_id, title, description, department, service,
                    status, external_ref, is_eval_seed, internal_notes
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'new', $7, TRUE, '[]'::jsonb)
                """,
                uuid4(),
                UUID(org_id),
                record["title"],
                record["description"],
                record.get("requester_department"),
                record.get("affected_service"),
                record["id"],
            )
    finally:
        await connection.close()
    return [record["id"] for record in records]


def seed_eval_tickets(database_url: str, org_id: str, count: int) -> list[str]:
    return asyncio.run(_seed_eval_tickets(database_url, org_id, count))


def wait_for_document(
    client: Phase5Client, token: str, document_id: str, timeout: float = 120
):
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        response = client.request("GET", f"/api/documents/{document_id}", token=token)
        assert response.status == 200, detail(response)
        last = response.body
        status = (last or {}).get("status")
        if status == "ready":
            return
        assert status != "failed", last
        time.sleep(0.3)
    pytest.fail(f"document {document_id} never became ready: {last!r}")


def wait_for_batch(
    client: Phase5Client, token: str, batch_id: str, timeout: float | None = None
) -> dict[str, Any]:
    """Poll a batch to a terminal status.

    Generous by default: a batch is N triage runs plus N judge calls, and the
    point of G5.4 is that it finishes — timing out here would report a
    slow batch as a broken one.
    """
    timeout = timeout or float(os.environ.get("PHASE5_BATCH_TIMEOUT_SECONDS", "600"))
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        response = client.request("GET", f"/api/eval/batches/{batch_id}", token=token)
        assert response.status == 200, detail(response)
        last = response.body
        if (last or {}).get("status") in BATCH_TERMINAL:
            return last
        time.sleep(2)
    pytest.fail(f"eval batch {batch_id} did not finish within {timeout}s: {last!r}")


@pytest.fixture(scope="session")
def phase5_client() -> Phase5Client:
    base_url = os.environ.get("PHASE5_BASE_URL", DEFAULT_BASE_URL)
    client = Phase5Client(
        base_url, os.environ.get("PHASE5_TOKEN_PATH", DEFAULT_TOKEN_PATH)
    )
    try:
        health = client.request("GET", "/api/health", timeout=3)
    except (TimeoutError, URLError, OSError) as exc:
        message = f"Phase 5 stack is not reachable at {base_url}: {exc}"
        pytest.fail(message) if truthy("PHASE5_REQUIRE_LIVE") else pytest.skip(message)
    if health.status != 200:
        message = f"Phase 5 health check failed: {detail(health)}"
        pytest.fail(message) if truthy("PHASE5_REQUIRE_LIVE") else pytest.skip(message)
    return client


@pytest.fixture(scope="session")
def phase5_database_url() -> str:
    """The database the live gates seed into.

    Deliberately NOT falling back to `DATABASE_URL`, which the Phase 4 suite
    also avoids. `DATABASE_URL` is whatever the *test process* is configured
    with — in the fast CI job that is an empty scratch database — while these
    gates need the database the running stack reads. When the two differ the
    symptom is a seeded user the API cannot find, which reads as an auth bug and
    is not one. Requiring the explicit variable makes the fast job skip cleanly
    instead.
    """
    value = os.environ.get("PHASE5_DATABASE_URL")
    if value:
        return value
    message = "PHASE5_DATABASE_URL is required to seed an isolated gate tenant"
    pytest.fail(message) if truthy("PHASE5_REQUIRE_LIVE") else pytest.skip(message)
    raise AssertionError("unreachable")
