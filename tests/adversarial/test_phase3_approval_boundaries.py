from __future__ import annotations

import copy
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from tests.phase3.conftest import (
    MockAdapterControl,
    Phase3Client,
    approval_detail,
    object_body,
    response_detail,
    run_detail,
    start_pending_run,
    wait_for_run_status,
)
from tests.phase3.helpers import (
    action_args,
    actions_from,
    approval_id,
    original_proposal,
)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def test_edited_approval_cannot_retarget_the_bundle_to_another_ticket(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
) -> None:
    """An edit may change proposed values, not the affected resource."""
    del phase3_evidence_ready
    approver_id = approver_user_ids[0]
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"retarget-source-{uuid4().hex}",
    )
    target_response = phase3_client.create_ticket(
        phase3_org_id,
        title=f"Unrelated same-tenant target {uuid4().hex}",
        description="This ticket was never presented on the approval card.",
        priority="P4",
    )
    target = object_body(target_response, "ticket")
    target_id = str(target["id"])

    retargeted = copy.deepcopy(original_proposal(approval))
    for action in actions_from(retargeted):
        action_args(action)["ticket_id"] = target_id

    decision = phase3_client.decide(
        phase3_org_id,
        approver_id,
        approval_id(approval),
        decision="edited",
        final_values=retargeted,
        feedback="adversarial resource-retarget probe",
    )

    if decision.status in {200, 202}:
        wait_for_run_status(
            phase3_client,
            org_id=phase3_org_id,
            run_id=run_id,
            statuses={"completed", "failed"},
        )
    target_after = object_body(
        phase3_client.get_ticket(phase3_org_id, target_id), "ticket"
    )
    assert decision.status in {400, 422}, (
        "a schema-valid edit retargeted every action to a ticket that was not "
        f"shown on the approval card; decision={response_detail(decision)}, "
        f"target_before={target!r}, target_after={target_after!r}"
    )
    persisted = approval_detail(phase3_client, phase3_org_id, approval_id(approval))
    assert persisted.get("decision") in {None, "pending"}, persisted
    assert target_after == target, (
        "a rejected retarget must not mutate the other ticket"
    )


def test_mock_adapter_call_recorder_does_not_cross_tenant_boundary(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    isolation_org_ids: tuple[str, str],
    mock_adapter_control: MockAdapterControl,
) -> None:
    del phase3_evidence_ready
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"recorder-isolation-{uuid4().hex}",
    )
    decision = phase3_client.decide(
        phase3_org_id,
        approver_user_ids[0],
        approval_id(approval),
        decision="approved",
    )
    assert decision.status in {200, 202}, response_detail(decision)
    completed = wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"completed", "failed"},
    )
    assert completed["status"] == "completed", completed
    assert mock_adapter_control.calls(run_id), (
        "probe needs at least one owner write call"
    )

    other_org = next(org for org in isolation_org_ids if org != phase3_org_id)
    separator = "&" if "?" in mock_adapter_control.recorder_path else "?"
    cross_org = phase3_client.request(
        "GET",
        f"{mock_adapter_control.recorder_path}{separator}{urlencode({'run_id': run_id})}",
        org_id=other_org,
    )
    assert cross_org.status in {403, 404}, (
        "a different tenant can read adapter calls containing ticket ids, note "
        f"content, and applied values: {response_detail(cross_org)}"
    )


@pytest.mark.asyncio
async def test_ticket_text_fault_directive_is_inert_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations import ticket_system

    async def no_test_hook_fault() -> None:
        return None

    monkeypatch.setattr(ticket_system, "_take_injected_fault", no_test_hook_fault)
    monkeypatch.setattr(
        ticket_system,
        "get_settings",
        lambda: SimpleNamespace(app_env="prod", mock_ticket_fault="none"),
    )
    adapter = ticket_system.MockTicketSystem(SimpleNamespace())  # type: ignore[arg-type]
    ticket = SimpleNamespace(
        description="ordinary user text [[FLOWFORGE_TICKET_FAULT:timeout]]"
    )

    # User-controlled ticket prose must not remain a fault-injection control in
    # a non-dev environment. No exception is the security property.
    await adapter._maybe_fail(ticket)


@pytest.mark.asyncio
async def test_ambiguous_transport_timeout_cannot_apply_an_external_write_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import write_tools
    from app.agents.tools import ToolContext

    class EmptyResult:
        def scalar_one_or_none(self) -> None:
            return None

    class FakeSession:
        async def execute(self, statement: object) -> EmptyResult:
            del statement
            return EmptyResult()

        def add(self, row: object) -> None:
            self.row = row

        async def flush(self) -> None:
            return None

    class AmbiguousAdapter:
        external_writes = 0

        async def assign_ticket(
            self, ticket_id: Any, org_id: Any, team: str
        ) -> dict[str, Any]:
            del ticket_id, org_id, team
            self.external_writes += 1
            # The remote side committed, but its response was lost. This is the
            # transport ambiguity an idempotency design must make safe.
            raise TimeoutError("response lost after the remote write committed")

    session = FakeSession()
    adapter = AmbiguousAdapter()
    monkeypatch.setattr(
        write_tools, "get_ticket_system", lambda *args, **kwargs: adapter
    )
    monkeypatch.setattr(write_tools, "WRITE_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(
        write_tools,
        "get_settings",
        lambda: SimpleNamespace(tool_timeout_seconds=1),
    )
    context = ToolContext(  # type: ignore[arg-type]
        session=session,
        org_id=uuid4(),
        run_id=uuid4(),
        actor="user:adversarial-probe",
    )

    with pytest.raises(write_tools.WriteToolError):
        await write_tools._execute_once(
            context,
            "assign_ticket",
            {"ticket_id": uuid4(), "team": "IT Infrastructure"},
            write_tools._Confirmation("assigned_team", "IT Infrastructure"),
        )

    assert adapter.external_writes == 1, (
        "the local ledger does not protect an external adapter when the remote "
        "write commits but the response times out; retry applied it twice"
    )


def test_every_write_tool_has_an_enforced_permission_check() -> None:
    from app.agents.write_tools import WRITE_TOOLS

    assert WRITE_TOOLS, "the approval-gated write registry must not be empty"
    missing = [
        tool.name for tool in WRITE_TOOLS.values() if tool.permission_check is None
    ]
    assert not missing, (
        "requires_approval metadata does not enforce anything in Tool.invoke; "
        f"write tools without the spec-required permission check: {missing!r}"
    )


def test_decided_approval_is_recovered_after_resume_enqueue_outage(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    repository_root: Path,
) -> None:
    """A Redis outage after CAS must not strand a one-shot decision forever."""
    del phase3_evidence_ready
    if not _truthy("PHASE3_MANAGE_STACK"):
        pytest.skip(
            "set PHASE3_MANAGE_STACK=1 on an isolated stack for this outage probe"
        )

    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"enqueue-outage-{uuid4().hex}",
    )
    compose_file = os.environ.get(
        "PHASE3_COMPOSE_FILE", str(repository_root / "infra" / "docker-compose.yml")
    )
    base_command = ["docker", "compose"]
    env_file = os.environ.get("PHASE3_ENV_FILE")
    if env_file:
        base_command.extend(["--env-file", env_file])
    base_command.extend(["-f", compose_file])

    stop = subprocess.run(
        [*base_command, "stop", "redis"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert stop.returncode == 0, stop.stdout + stop.stderr
    try:
        decision = phase3_client.decide(
            phase3_org_id,
            approver_user_ids[0],
            approval_id(approval),
            decision="rejected",
            feedback="queue outage recovery probe",
        )
    finally:
        restart = subprocess.run(
            [*base_command, "up", "-d", "redis", "worker"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert restart.returncode == 0, restart.stdout + restart.stderr

    assert decision.status in {200, 202, 500, 503}, response_detail(decision)
    persisted = approval_detail(phase3_client, phase3_org_id, approval_id(approval))
    if persisted.get("decision") in {None, "pending"}:
        # Clean failure before the compare-and-swap committed: the human can
        # retry when the queue is healthy, so this is not a stranded decision.
        assert run_detail(phase3_client, phase3_org_id, run_id).get("status") == (
            "awaiting_approval"
        )
        return

    deadline = time.monotonic() + 10
    last = run_detail(phase3_client, phase3_org_id, run_id)
    while time.monotonic() < deadline and last.get("status") not in {
        "completed",
        "rejected",
        "failed",
    }:
        time.sleep(0.25)
        last = run_detail(phase3_client, phase3_org_id, run_id)

    assert last.get("status") in {"completed", "rejected", "failed"}, (
        "the decision CAS committed before resume enqueue failed, and worker "
        f"startup does not recover decided approvals left awaiting: {last!r}"
    )
