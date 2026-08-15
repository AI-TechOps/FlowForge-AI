from __future__ import annotations

import asyncio
import inspect
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest

from tests.phase4.conftest import (
    Phase4Client,
    PrincipalToken,
    response_detail,
)


def _asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


async def _insert_user(
    database_url: str,
    *,
    org_id: str,
    email: str,
    role: str = "operator",
) -> str:
    import asyncpg

    user_id = uuid4()
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await connection.execute(
            "INSERT INTO users (id, org_id, email, auth_subject) VALUES ($1, $2, $3, NULL)",
            user_id,
            UUID(org_id),
            email,
        )
        await connection.execute(
            "INSERT INTO user_roles (user_id, role) VALUES ($1, $2)",
            user_id,
            role,
        )
    finally:
        await connection.close()
    return str(user_id)


async def _insert_ticket_run(
    database_url: str,
    *,
    org_id: str,
    marker: str,
    status: str,
    attempts: int = 0,
    old_started_at: bool = False,
) -> tuple[str, str]:
    import asyncpg

    ticket_id = uuid4()
    run_id = uuid4()
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await connection.execute(
            """
            INSERT INTO tickets (id, org_id, title, description, priority)
            VALUES ($1, $2, $3, $4, 'P4')
            """,
            ticket_id,
            UUID(org_id),
            f"Phase 4 adversarial {marker}",
            f"Confidential tenant marker {marker}",
        )
        await connection.execute(
            """
            INSERT INTO runs (
                id, org_id, ticket_id, status, agent_version, output, evidence,
                attempts, started_at, finished_at
            )
            VALUES (
                $1, $2, $3, $4::run_status, 'phase4-adversarial', $5::jsonb, $6::jsonb,
                $7,
                CASE WHEN $8 THEN now() - interval '2 hours' ELSE now() END,
                CASE WHEN $9 THEN now() ELSE NULL END
            )
            """,
            run_id,
            UUID(org_id),
            ticket_id,
            status,
            json.dumps({"summary": marker, "citations": []}),
            json.dumps([{"text": marker}]),
            attempts,
            old_started_at,
            status == "completed",
        )
    finally:
        await connection.close()
    return str(ticket_id), str(run_id)


async def _run_state(database_url: str, run_id: str) -> tuple[str, str | None, int]:
    import asyncpg

    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        row = await connection.fetchrow(
            "SELECT status, failure_reason, attempts FROM runs WHERE id = $1",
            UUID(run_id),
        )
        approval_count = await connection.fetchval(
            "SELECT count(*) FROM approvals WHERE run_id = $1", UUID(run_id)
        )
    finally:
        await connection.close()
    assert row is not None
    return str(row["status"]), row["failure_reason"], int(approval_count)


async def _ticket_status(database_url: str, ticket_id: str) -> str:
    import asyncpg

    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        status = await connection.fetchval(
            "SELECT status FROM tickets WHERE id = $1", UUID(ticket_id)
        )
    finally:
        await connection.close()
    assert status is not None
    return str(status)


def test_phase4_role_claim_injection_cannot_elevate_an_operator(
    phase4_client: Phase4Client,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    operator = phase4_principals["a"]["operator"]
    token_response = phase4_client.request(
        "POST",
        phase4_client.token_path,
        json_body={
            "email": operator.email,
            "subject": operator.subject,
            "roles": ["administrator", "approver"],
            "org_id": phase4_principals["b"]["operator"].org_id,
        },
    )
    assert token_response.status == 200, response_detail(token_response)
    assert isinstance(token_response.body, dict), response_detail(token_response)
    token = token_response.body.get("access_token")
    assert isinstance(token, str) and token

    response = phase4_client.request("GET", "/api/documents", token=token)
    assert response.status == 403, response_detail(response)


def test_phase4_first_login_rejects_email_already_bound_in_another_tenant(
    phase4_client: Phase4Client,
    phase4_database_url: str,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    """An already-linked row must still count when detecting email ambiguity."""
    linked = phase4_principals["a"]["operator"]
    asyncio.run(
        _insert_user(
            phase4_database_url,
            org_id=phase4_principals["b"]["operator"].org_id,
            email=linked.email,
        )
    )
    token = phase4_client.issue_token(
        email=linked.email,
        subject=f"second-subject|{uuid4()}",
    )
    response = phase4_client.request("GET", "/api/me", token=token)
    assert response.status == 403, (
        "one email now identifies rows in two organizations; filtering the "
        "ambiguity check to only unlinked rows silently binds the second subject: "
        f"{response_detail(response)}"
    )


def test_phase4_approval_detail_cannot_follow_a_cross_tenant_relationship(
    phase4_client: Phase4Client,
    phase4_database_url: str,
    phase4_principals: dict[str, dict[str, PrincipalToken]],
) -> None:
    """Every tenant-model hop must be scoped, even when a bad FK row exists."""
    marker = f"cross-tenant-approval-{uuid4().hex}"
    _, foreign_run_id = asyncio.run(
        _insert_ticket_run(
            phase4_database_url,
            org_id=phase4_principals["b"]["operator"].org_id,
            marker=marker,
            status="awaiting_approval",
        )
    )
    approval_id = uuid4()

    async def insert_mismatched_approval() -> None:
        import asyncpg

        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.execute(
                """
                INSERT INTO approvals (id, org_id, run_id, original_proposal)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                approval_id,
                UUID(phase4_principals["a"]["approver"].org_id),
                UUID(foreign_run_id),
                json.dumps([]),
            )
        finally:
            await connection.close()

    asyncio.run(insert_mismatched_approval())
    response = phase4_client.request(
        "GET",
        f"/api/approvals/{approval_id}",
        token=phase4_principals["a"]["approver"].access_token,
    )
    assert response.status == 404, response_detail(response)
    assert marker not in response.text, response_detail(response)


def test_phase4_duplicate_execute_delivery_cannot_reopen_a_terminal_run(
    phase4_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import runner

    marker = f"terminal-replay-{uuid4().hex}"
    org_id = str(uuid4())

    async def seed() -> str:
        import asyncpg

        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                UUID(org_id),
                f"Phase 4 terminal replay {marker}",
            )
        finally:
            await connection.close()
        _, run_id = await _insert_ticket_run(
            phase4_database_url,
            org_id=org_id,
            marker=marker,
            status="completed",
        )
        return run_id

    run_id = asyncio.run(seed())

    @asynccontextmanager
    async def fake_checkpointer():
        yield object()

    class DuplicateGraph:
        async def ainvoke(self, state: object, config: object) -> dict[str, object]:
            del state, config
            return {
                "__interrupt__": [{"value": "duplicate"}],
                "evidence": [],
                "result": {"summary": marker, "citations": []},
                "confidence": 1.0,
                "proposed_actions": [],
                "risk_class": "low",
            }

    monkeypatch.setattr(runner, "checkpointer", fake_checkpointer)
    monkeypatch.setattr(runner, "build_graph", lambda saver: DuplicateGraph())

    async def exercise_duplicate() -> tuple[str, str, int]:
        from app.db import engine

        try:
            result = await runner.execute_run({}, run_id, org_id)
            status, _, approvals = await _run_state(phase4_database_url, run_id)
            return result, status, approvals
        finally:
            await engine.dispose()

    result, status, approvals = asyncio.run(exercise_duplicate())
    assert result == "completed"
    assert status == "completed"
    assert approvals == 0, "a duplicate initial job created a new approval"


def test_phase4_duplicate_execute_delivery_cannot_claim_an_active_run(
    phase4_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovery claim must be distinguishable from a still-active worker."""
    from app.agents import runner

    marker = f"active-replay-{uuid4().hex}"
    org_id = str(uuid4())

    async def seed() -> str:
        import asyncpg

        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                UUID(org_id),
                f"Phase 4 active replay {marker}",
            )
        finally:
            await connection.close()
        _, run_id = await _insert_ticket_run(
            phase4_database_url,
            org_id=org_id,
            marker=marker,
            status="running",
            attempts=1,
        )
        return run_id

    run_id = asyncio.run(seed())

    @asynccontextmanager
    async def fake_checkpointer():
        yield object()

    class DuplicateGraph:
        async def ainvoke(self, state: object, config: object) -> dict[str, object]:
            del state, config
            return {
                "__interrupt__": [{"value": "duplicate"}],
                "evidence": [],
                "result": {"summary": marker, "citations": []},
                "confidence": 1.0,
                "proposed_actions": [],
                "risk_class": "low",
            }

    monkeypatch.setattr(runner, "checkpointer", fake_checkpointer)
    monkeypatch.setattr(runner, "build_graph", lambda saver: DuplicateGraph())

    async def exercise_duplicate() -> tuple[str, str, int]:
        from app.db import engine

        try:
            result = await runner.execute_run({}, run_id, org_id)
            status, _, approvals = await _run_state(phase4_database_url, run_id)
            return result, status, approvals
        finally:
            await engine.dispose()

    result, status, approvals = asyncio.run(exercise_duplicate())
    assert result == "running", "a duplicate delivery claimed a run already in progress"
    assert status == "running"
    assert approvals == 0, "the duplicate active delivery created an approval"


def test_phase4_duplicate_resume_delivery_cannot_claim_an_active_execution(
    phase4_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second resume must not enter a graph another worker is executing."""
    from app.agents import runner

    marker = f"active-resume-{uuid4().hex}"
    org_id = str(uuid4())

    async def seed() -> str:
        import asyncpg

        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                UUID(org_id),
                f"Phase 4 active resume {marker}",
            )
        finally:
            await connection.close()
        _, run_id = await _insert_ticket_run(
            phase4_database_url,
            org_id=org_id,
            marker=marker,
            status="executing",
        )
        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.execute(
                """
                INSERT INTO approvals (
                    id, org_id, run_id, status, decision, original_proposal, decided_at
                )
                VALUES ($1, $2, $3, 'decided', 'rejected', '[]'::jsonb, now())
                """,
                uuid4(),
                UUID(org_id),
                UUID(run_id),
            )
        finally:
            await connection.close()
        return run_id

    run_id = asyncio.run(seed())

    @asynccontextmanager
    async def fake_checkpointer():
        yield object()

    class DuplicateGraph:
        async def ainvoke(self, command: object, config: object) -> dict[str, object]:
            del command, config
            return {"rejected": True}

    monkeypatch.setattr(runner, "checkpointer", fake_checkpointer)
    monkeypatch.setattr(runner, "build_graph", lambda saver: DuplicateGraph())

    async def exercise_duplicate() -> tuple[str, str]:
        from app.db import engine

        try:
            result = await runner.resume_run({}, run_id, org_id)
            status, _, _ = await _run_state(phase4_database_url, run_id)
            return result, status
        finally:
            await engine.dispose()

    result, status = asyncio.run(exercise_duplicate())
    assert result == "executing", "a duplicate resume entered an active graph"
    assert status == "executing"


def test_phase4_recovery_handles_running_jobs_and_dead_letter_boundary(
    phase4_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import runner

    org_id = str(uuid4())
    marker = f"stranded-running-{uuid4().hex}"

    async def seed() -> tuple[str, str]:
        import asyncpg

        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                UUID(org_id),
                f"Phase 4 recovery {marker}",
            )
        finally:
            await connection.close()
        _, retry_id = await _insert_ticket_run(
            phase4_database_url,
            org_id=org_id,
            marker=f"{marker}-retry",
            status="running",
            attempts=1,
            old_started_at=True,
        )
        _, exhausted_id = await _insert_ticket_run(
            phase4_database_url,
            org_id=org_id,
            marker=f"{marker}-exhausted",
            status="running",
            attempts=runner.get_settings().max_run_attempts,
            old_started_at=True,
        )
        return retry_id, exhausted_id

    retry_id, exhausted_id = asyncio.run(seed())
    enqueued: list[tuple[str, str]] = []

    async def capture_run(run_id: object, queued_org_id: object) -> None:
        enqueued.append((str(run_id), str(queued_org_id)))

    async def capture_resume(run_id: object, queued_org_id: object) -> None:
        del run_id, queued_org_id

    monkeypatch.setattr(runner, "enqueue_run", capture_run)
    monkeypatch.setattr(runner, "enqueue_resume", capture_resume)

    async def exercise_recovery() -> tuple[str, str | None]:
        from app.db import engine

        try:
            await runner.recover_stranded_runs()
            status, failure_reason, _ = await _run_state(phase4_database_url, exhausted_id)
            return status, failure_reason
        finally:
            await engine.dispose()

    status, failure_reason = asyncio.run(exercise_recovery())
    failures: list[str] = []
    if (retry_id, org_id) not in enqueued:
        failures.append(
            "a worker crash leaves initial triage in running, but startup "
            "recovery did not re-enqueue it"
        )
    if (status, failure_reason) != ("failed", "dead_letter"):
        failures.append(
            "a running job already at max attempts remained "
            f"{status}/{failure_reason} instead of failed/dead_letter"
        )
    assert not failures, "; ".join(failures)


def test_phase4_worker_finalization_cannot_mutate_a_foreign_ticket(
    phase4_database_url: str,
) -> None:
    """Worker relationship hops need org scoping just like API relationship hops."""
    from app.agents import runner

    run_org_id = uuid4()
    ticket_org_id = uuid4()
    ticket_id = uuid4()
    run_id = uuid4()

    async def seed() -> None:
        import asyncpg

        connection = await asyncpg.connect(_asyncpg_url(phase4_database_url))
        try:
            await connection.executemany(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                [
                    (run_org_id, f"Phase 4 worker run org {run_org_id}"),
                    (ticket_org_id, f"Phase 4 worker ticket org {ticket_org_id}"),
                ],
            )
            await connection.execute(
                """
                INSERT INTO tickets (id, org_id, title, description, priority)
                VALUES ($1, $2, 'Foreign ticket', 'Must remain untouched', 'P4')
                """,
                ticket_id,
                ticket_org_id,
            )
            await connection.execute(
                """
                INSERT INTO runs (id, org_id, ticket_id, status, agent_version, output)
                VALUES ($1, $2, $3, 'executing', 'phase4-adversarial', '{}'::jsonb)
                """,
                run_id,
                run_org_id,
                ticket_id,
            )
        finally:
            await connection.close()

    async def exercise_finalization() -> str:
        from app.db import async_session_factory, engine
        from app.models import Run

        try:
            async with async_session_factory() as session:
                run = await session.get(Run, run_id)
                assert run is not None
                await runner._finalize_decision(
                    session,
                    run,
                    {"executed_actions": []},
                )
            return await _ticket_status(phase4_database_url, str(ticket_id))
        finally:
            await engine.dispose()

    asyncio.run(seed())
    status = asyncio.run(exercise_finalization())
    assert status == "new", (
        "finalizing an org-A run followed its unscoped ticket_id and changed "
        "org B's ticket to actioned"
    )


def test_phase4_background_job_payloads_carry_the_acting_user() -> None:
    from app.ingestion import queue

    missing: list[str] = []
    for function in (queue.enqueue_ingest, queue.enqueue_run, queue.enqueue_resume):
        parameter_names = inspect.signature(function).parameters
        if not any("user" in name for name in parameter_names):
            missing.append(function.__name__)
    assert not missing, (
        "spec 05 requires org_id plus acting user id in background job payloads; "
        f"missing user context: {missing!r}"
    )


def test_phase4_reset_corpus_cannot_wipe_one_org_and_authenticate_as_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import reset_corpus

    source = tmp_path / "policy.md"
    source.write_text("# Synthetic policy\n")
    authorization_headers: list[str | None] = []

    def token_for_arguments(*args: object, **kwargs: object) -> dict[str, str]:
        return {"Authorization": f"Bearer context:{args!r}:{kwargs!r}"}

    def capture(request: object, timeout: float) -> io.BytesIO:
        del timeout
        authorization_headers.append(request.get_header("Authorization"))
        return io.BytesIO(b'{"id":"synthetic-document"}')

    monkeypatch.setattr(reset_corpus, "auth_header", token_for_arguments)
    monkeypatch.setattr(reset_corpus.urllib.request, "urlopen", capture)

    reset_corpus._upload("http://flowforge.test", uuid4(), source)
    reset_corpus._upload("http://flowforge.test", uuid4(), source)
    assert authorization_headers[0] != authorization_headers[1], (
        "--org-id controls the direct database wipe, but both uploads use the "
        "same default demo token; selecting another org can delete that org's "
        "corpus and re-ingest everything into the demo tenant"
    )


def test_phase4_auth0_pkce_callback_is_bound_to_the_login_with_state(
    repository_root: Path,
) -> None:
    source = (repository_root / "frontend" / "src" / "auth.ts").read_text()
    assert "state:" in source, "the Auth0 authorize request sends no state nonce"
    assert (
        '.get("state")' in source or ".get('state')" in source
    ), "the Auth0 callback never reads the returned state"
    assert "STATE_KEY" in source, "the expected state is not persisted and compared"


def test_phase4_local_auth_provider_is_refused_in_production() -> None:
    from app.auth.provider import get_auth_provider
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://unused:unused@localhost/unused",
        redis_url="redis://localhost:6379/15",
        app_env="prod",
        auth_provider="local",
    )
    with pytest.raises(ValueError, match="never prod"):
        get_auth_provider(settings)
