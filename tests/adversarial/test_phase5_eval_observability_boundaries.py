from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tests.phase5.conftest import (
    Phase5Client,
    connect,
    detail,
    new_tenant,
    runtime_module,
)


def test_phase5_same_model_family_cannot_judge_itself() -> None:
    """D19 requires different model families, not merely different tags."""
    Settings = runtime_module("app.config").Settings

    with pytest.raises(ValueError, match="differ"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://unused:unused@localhost/unused",
            redis_url="redis://localhost:6379/15",
            llm_provider="ollama",
            triage_model="llama3.1:8b",
            judge_model="llama3.1:70b",
        )


def test_phase5_operator_still_sees_average_tokens_per_run(
    phase5_client: Phase5Client,
    phase5_database_url: str,
) -> None:
    """D19 restricts spend and accuracy, while tokens remain a shared metric."""
    tenant = new_tenant(phase5_client, phase5_database_url)

    async def seed() -> None:
        connection = await connect(phase5_database_url)
        try:
            ticket_id = uuid4()
            run_id = uuid4()
            await connection.execute(
                """
                INSERT INTO tickets (id, org_id, title, description, internal_notes)
                VALUES ($1, $2, 'Token metric probe', 'Synthetic', '[]'::jsonb)
                """,
                ticket_id,
                UUID(tenant.org_id),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    id, org_id, ticket_id, status, agent_version, started_at,
                    finished_at, created_at
                )
                VALUES ($1, $2, $3, 'completed', 'phase5-adversarial', now(), now(), now())
                """,
                run_id,
                UUID(tenant.org_id),
                ticket_id,
            )
            await connection.execute(
                """
                INSERT INTO audit_log (
                    id, org_id, run_id, actor, tool, payload, result,
                    tokens_in, tokens_out, created_at
                )
                VALUES (
                    $1, $2, $3, 'agent', 'llm.classify', '{}'::jsonb,
                    '{}'::jsonb, 20, 10, now()
                )
                """,
                uuid4(),
                UUID(tenant.org_id),
                run_id,
            )
        finally:
            await connection.close()

    asyncio.run(seed())
    response = phase5_client.request("GET", "/api/metrics/summary", token=tenant.operator)
    assert response.status == 200, detail(response)
    assert response.body.get("avg_tokens_per_run") == pytest.approx(30.0), (
        "spec 06 says every role sees average tokens/run; only cost and "
        f"evaluation accuracy are administrator-only: {response.body!r}"
    )


def test_phase5_batch_detail_does_not_follow_a_cross_tenant_result(
    phase5_client: Phase5Client,
    phase5_database_url: str,
) -> None:
    """Every result returned for a scoped batch must belong to that tenant."""
    owner = new_tenant(phase5_client, phase5_database_url)
    neighbour = new_tenant(phase5_client, phase5_database_url)
    batch_id = uuid4()
    marker = f"foreign-{uuid4().hex}"

    async def seed() -> None:
        connection = await connect(phase5_database_url)
        try:
            ticket_id = uuid4()
            await connection.execute(
                """
                INSERT INTO eval_batches (
                    id, org_id, agent_version, llm_provider, triage_model,
                    judge_model, status, total_tickets, summary
                )
                VALUES (
                    $1, $2, 'phase5-adversarial', 'fake', 'triage', 'judge',
                    'completed', 0, '{}'::jsonb
                )
                """,
                batch_id,
                UUID(owner.org_id),
            )
            await connection.execute(
                """
                INSERT INTO tickets (id, org_id, title, description, internal_notes)
                VALUES ($1, $2, $3, 'Must not cross the boundary', '[]'::jsonb)
                """,
                ticket_id,
                UUID(neighbour.org_id),
                marker,
            )
            await connection.execute(
                """
                INSERT INTO eval_results (
                    id, org_id, batch_id, ticket_id, seed_ref, expected,
                    actual, scores
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, '{}'::jsonb)
                """,
                uuid4(),
                UUID(neighbour.org_id),
                batch_id,
                ticket_id,
                marker,
                json.dumps({"confidential": marker}),
                json.dumps({"recommended_resolution": marker}),
            )
        finally:
            await connection.close()

    asyncio.run(seed())
    response = phase5_client.request("GET", f"/api/eval/batches/{batch_id}", token=owner.admin)
    assert response.status == 200, detail(response)
    assert response.body["results"] == [], (
        "an org-A batch returned an org-B result, including its expected and "
        f"actual output: {response.body!r}"
    )
    assert marker not in response.text, detail(response)


def test_phase5_metrics_window_excludes_an_old_eval_batch(
    phase5_client: Phase5Client,
    phase5_database_url: str,
) -> None:
    """The time-window parameter applies to every metric in the summary."""
    tenant = new_tenant(phase5_client, phase5_database_url)
    batch_id = uuid4()

    async def seed() -> None:
        connection = await connect(phase5_database_url)
        try:
            old = datetime.now(UTC) - timedelta(days=200)
            await connection.execute(
                """
                INSERT INTO eval_batches (
                    id, org_id, agent_version, llm_provider, triage_model,
                    judge_model, status, total_tickets, summary, created_at,
                    started_at, finished_at
                )
                VALUES (
                    $1, $2, 'old-version', 'ollama', 'triage', 'judge',
                    'completed', 20, $3::jsonb, $4, $4, $4
                )
                """,
                batch_id,
                UUID(tenant.org_id),
                json.dumps(
                    {
                        "accuracy_overall": 0.99,
                        "retrieval_hit_at_k": 0.98,
                        "grounded_rate": 0.97,
                    }
                ),
                old,
            )
        finally:
            await connection.close()

    asyncio.run(seed())
    response = phase5_client.request(
        "GET", "/api/metrics/summary?window_days=30", token=tenant.admin
    )
    assert response.status == 200, detail(response)
    assert response.body["evaluation_accuracy"] is None, response.body
    assert response.body["retrieval_success"] is None, response.body
    assert response.body["grounded_rate"] is None, response.body
    assert response.body["latest_eval_batch_id"] is None, response.body


def test_phase5_eval_endpoint_does_not_silently_drop_unlabelled_seed_tickets(
    phase5_client: Phase5Client,
    phase5_database_url: str,
) -> None:
    """G5.4 is 100% of eval seeds, not 100% of a filtered subset."""
    tenant = new_tenant(phase5_client, phase5_database_url)

    async def seed() -> None:
        connection = await connect(phase5_database_url)
        try:
            for external_ref in ("EVAL-001", f"UNLABELLED-{uuid4().hex}"):
                await connection.execute(
                    """
                    INSERT INTO tickets (
                        id, org_id, title, description, external_ref,
                        is_eval_seed, internal_notes
                    )
                    VALUES ($1, $2, $3, 'Synthetic eval seed', $4, TRUE, '[]'::jsonb)
                    """,
                    uuid4(),
                    UUID(tenant.org_id),
                    f"Phase 5 seed {external_ref}",
                    external_ref,
                )
        finally:
            await connection.close()

    asyncio.run(seed())
    response = phase5_client.request("POST", "/api/eval/run", token=tenant.admin)
    if response.status == 202:
        assert response.body["total_tickets"] == 2, (
            "the endpoint accepted a batch but silently excluded an is_eval_seed "
            f"ticket whose label was missing: {response.body!r}"
        )
    else:
        assert response.status in {409, 422}, detail(response)


def test_phase5_eval_run_does_not_change_the_source_ticket(
    phase5_database_url: str,
) -> None:
    """An eval graph with no write node must also have no finalize-side write."""
    runner = runtime_module("app.agents.runner")

    org_id = uuid4()
    ticket_id = uuid4()
    batch_id = uuid4()
    run_id = uuid4()

    async def seed() -> None:
        connection = await connect(phase5_database_url)
        try:
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                org_id,
                f"Phase 5 eval mutation {org_id}",
            )
            await connection.execute(
                """
                INSERT INTO tickets (
                    id, org_id, title, description, status, is_eval_seed,
                    internal_notes
                )
                VALUES ($1, $2, 'Eval source', 'Must stay new', 'new', TRUE, '[]'::jsonb)
                """,
                ticket_id,
                org_id,
            )
            await connection.execute(
                """
                INSERT INTO eval_batches (
                    id, org_id, agent_version, llm_provider, triage_model,
                    judge_model, status, total_tickets
                )
                VALUES ($1, $2, 'phase5-adversarial', 'fake', 'triage', 'judge', 'running', 1)
                """,
                batch_id,
                org_id,
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    id, org_id, ticket_id, status, agent_version, eval_batch_id
                )
                VALUES ($1, $2, $3, 'running', 'phase5-adversarial', $4)
                """,
                run_id,
                org_id,
                ticket_id,
                batch_id,
            )
        finally:
            await connection.close()

    async def finalize() -> tuple[str, str]:
        database = runtime_module("app.db")
        Run = runtime_module("app.models").Run

        try:
            async with database.async_session_factory() as session:
                run = await session.get(Run, run_id)
                assert run is not None
                result = await runner._finalize(
                    session,
                    run,
                    {
                        "evidence": [{"chunk_id": "synthetic"}],
                        "result": {
                            "summary": "Synthetic eval output",
                            "citations": [{"chunk_id": "synthetic"}],
                        },
                        "confidence": 1.0,
                    },
                )
            connection = await connect(phase5_database_url)
            try:
                status = await connection.fetchval(
                    "SELECT status FROM tickets WHERE id = $1", ticket_id
                )
            finally:
                await connection.close()
            return result, str(status)
        finally:
            await database.engine.dispose()

    asyncio.run(seed())
    result, ticket_status = asyncio.run(finalize())
    assert result == "completed"
    assert ticket_status == "new", (
        "the eval graph has no execute node, but runner finalization still "
        "changed its source ticket to triaged"
    )


def test_phase5_run_jobs_are_not_published_before_their_rows_commit(
    phase5_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker must be able to see a run as soon as its job is published."""
    evaluation = runtime_module("app.api.evaluation")
    Principal = runtime_module("app.auth.principal").Principal
    Role = runtime_module("app.models").Role

    org_id = uuid4()
    user_id = uuid4()
    ticket_id = uuid4()
    visible_at_enqueue: list[bool] = []

    async def seed() -> None:
        connection = await connect(phase5_database_url)
        try:
            await connection.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                org_id,
                f"Phase 5 publish ordering {org_id}",
            )
            await connection.execute(
                """
                INSERT INTO users (id, org_id, email, auth_subject)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                org_id,
                f"phase5-publish-{user_id}@adversarial.test",
                f"phase5|{user_id}",
            )
            await connection.execute(
                """
                INSERT INTO tickets (
                    id, org_id, title, description, external_ref,
                    is_eval_seed, internal_notes
                )
                VALUES ($1, $2, 'Publish ordering', 'Synthetic', 'ADV-PUBLISH', TRUE, '[]'::jsonb)
                """,
                ticket_id,
                org_id,
            )
        finally:
            await connection.close()

    async def observe_run(run_id: UUID, *args: object, **kwargs: object) -> None:
        del args, kwargs
        connection = await connect(phase5_database_url)
        try:
            visible = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM runs WHERE id = $1)", run_id
            )
            visible_at_enqueue.append(bool(visible))
        finally:
            await connection.close()

    async def ignore_batch(*args: object, **kwargs: object) -> None:
        del args, kwargs

    monkeypatch.setattr(
        evaluation,
        "load_labels",
        lambda: {"ADV-PUBLISH": {"id": "ADV-PUBLISH", "labels": {}}},
    )
    monkeypatch.setattr(evaluation, "enqueue_run", observe_run)
    monkeypatch.setattr(evaluation, "enqueue_eval_batch", ignore_batch)

    principal = Principal(
        user_id=user_id,
        org_id=org_id,
        email=f"phase5-publish-{user_id}@adversarial.test",
        subject=f"phase5|{user_id}",
        roles=frozenset({Role.administrator}),
    )

    async def exercise() -> None:
        database = runtime_module("app.db")

        try:
            async with database.async_session_factory() as session:
                await evaluation.start_eval_batch(session=session, principal=principal)
        finally:
            await database.engine.dispose()

    asyncio.run(seed())
    asyncio.run(exercise())
    assert visible_at_enqueue == [True], (
        "the run job was published while its row was still invisible to a "
        "worker connection; an immediate pickup returns missing"
    )


def test_phase5_regression_table_contains_distinct_agent_versions(
    repository_root: Path,
) -> None:
    """G5.5 requires different versions, not duplicate rows for one version."""
    text = (repository_root / "eval" / "baseline.md").read_text(encoding="utf-8")
    section = text.split("## Phase 5 eval batches", 1)
    assert len(section) == 2, "missing Phase 5 regression table"

    rows: list[list[str]] = []
    for line in section[1].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and not all(set(cell) <= {"-", ":"} for cell in cells):
            rows.append(cells)

    assert len(rows) >= 3, rows
    header, *data = rows
    version_column = next(
        index for index, name in enumerate(header) if name.lower() == "agent_version"
    )
    versions = {row[version_column] for row in data}
    assert len(versions) >= 2, (
        "G5.5 requires batches at different agent_versions, but the regression "
        f"table repeats only {sorted(versions)!r}"
    )
