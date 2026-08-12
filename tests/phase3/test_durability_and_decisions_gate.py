from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from .conftest import (
    MockAdapterControl,
    Phase3Client,
    approval_detail,
    object_body,
    response_detail,
    run_detail,
    start_pending_run,
    wait_for_run_status,
)
from .helpers import (
    approval_card_contract,
    approval_id,
    assert_each_action_called_once,
    decision_snapshot,
    original_proposal,
)


def test_g3_1_paused_run_survives_backend_restart_then_resumes_to_completion(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
    restart_backend: Callable[[], None],
) -> None:
    del phase3_evidence_ready
    approver_id = approver_user_ids[0]
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"durability-{uuid4().hex}",
    )
    approval_card_contract(approval)
    proposal_before = original_proposal(approval)
    approval_id_value = approval_id(approval)
    assert (
        run_detail(phase3_client, phase3_org_id, run_id)["status"]
        == "awaiting_approval"
    )

    restart_backend()

    paused_after_restart = run_detail(phase3_client, phase3_org_id, run_id)
    approval_after_restart = approval_detail(
        phase3_client, phase3_org_id, approval_id_value
    )
    assert paused_after_restart["status"] == "awaiting_approval"
    assert original_proposal(approval_after_restart) == proposal_before

    decision = phase3_client.decide(
        phase3_org_id,
        approver_id,
        approval_id_value,
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
    assert_each_action_called_once(proposal_before, mock_adapter_control.calls(run_id))


def test_g3_2_rejection_records_feedback_and_executes_zero_adapter_writes(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
) -> None:
    del phase3_evidence_ready
    approver_id = approver_user_ids[0]
    ticket_id, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"reject-{uuid4().hex}",
    )
    approval_id_value = approval_id(approval)
    ticket_before = object_body(
        phase3_client.get_ticket(phase3_org_id, ticket_id), "ticket"
    )
    assert mock_adapter_control.calls(run_id) == []
    feedback = f"Rejected by G3.2 gate {uuid4().hex}"

    decision = phase3_client.decide(
        phase3_org_id,
        approver_id,
        approval_id_value,
        decision="rejected",
        feedback=feedback,
    )
    assert decision.status in {200, 202}, response_detail(decision)
    rejected = wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"rejected", "failed"},
    )
    assert rejected["status"] == "rejected", rejected
    persisted = approval_detail(phase3_client, phase3_org_id, approval_id_value)
    assert persisted.get("decision") == "rejected", persisted
    assert persisted.get("approver_user_id") == approver_id, persisted
    assert persisted.get("feedback") == feedback, persisted
    assert original_proposal(persisted) == original_proposal(approval)
    assert (
        mock_adapter_control.calls(run_id) == []
    ), "reject must execute zero mock adapter write calls"
    ticket_after = object_body(
        phase3_client.get_ticket(phase3_org_id, ticket_id), "ticket"
    )
    assert ticket_after == ticket_before, "reject changed the affected ticket"


def test_g3_3_replayed_approval_is_a_noop_with_one_durable_execution_per_action(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
    tool_execution_rows: Callable[[str], list[dict[str, object]]],
) -> None:
    del phase3_evidence_ready
    approver_id = approver_user_ids[0]
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"idempotency-{uuid4().hex}",
    )
    approval_id_value = approval_id(approval)
    proposal = original_proposal(approval)

    first = phase3_client.decide(
        phase3_org_id, approver_id, approval_id_value, decision="approved"
    )
    assert first.status in {200, 202}, response_detail(first)
    completed = wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"completed", "failed"},
    )
    assert completed["status"] == "completed", completed
    calls_before = mock_adapter_control.calls(run_id)
    executions_before = tool_execution_rows(run_id)
    assert_each_action_called_once(proposal, calls_before)
    assert len(executions_before) == len(calls_before), executions_before
    keys = {(row.get("tool"), row.get("args_hash")) for row in executions_before}
    assert len(keys) == len(
        executions_before
    ), "tool execution idempotency keys are not unique"
    assert all(row.get("result") is not None for row in executions_before)

    replay = phase3_client.decide(
        phase3_org_id, approver_id, approval_id_value, decision="approved"
    )
    assert replay.status == 409, response_detail(replay)
    time.sleep(0.5)
    assert mock_adapter_control.calls(run_id) == calls_before
    assert tool_execution_rows(run_id) == executions_before


def test_g3_7_second_decision_returns_409_without_changing_rejected_state(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
) -> None:
    del phase3_evidence_ready
    first_user, second_user = approver_user_ids
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"one-shot-{uuid4().hex}",
    )
    approval_id_value = approval_id(approval)
    first = phase3_client.decide(
        phase3_org_id,
        first_user,
        approval_id_value,
        decision="rejected",
        feedback="first decision wins",
    )
    assert first.status in {200, 202}, response_detail(first)
    wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"rejected"},
    )
    before = approval_detail(phase3_client, phase3_org_id, approval_id_value)

    second = phase3_client.decide(
        phase3_org_id,
        second_user,
        approval_id_value,
        decision="approved",
    )
    assert second.status == 409, response_detail(second)
    after = approval_detail(phase3_client, phase3_org_id, approval_id_value)
    assert decision_snapshot(after) == decision_snapshot(before)
    assert run_detail(phase3_client, phase3_org_id, run_id)["status"] == "rejected"
    assert mock_adapter_control.calls(run_id) == []


def test_g3_7_concurrent_decisions_have_one_winner_and_no_duplicate_execution(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
) -> None:
    del phase3_evidence_ready
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"concurrent-{uuid4().hex}",
    )
    approval_id_value = approval_id(approval)
    proposal = original_proposal(approval)
    barrier = Barrier(3)

    def decide(user_id: str):
        barrier.wait(timeout=10)
        return phase3_client.decide(
            phase3_org_id,
            user_id,
            approval_id_value,
            decision="approved",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(decide, user_id) for user_id in approver_user_ids]
        barrier.wait(timeout=10)
        responses = [future.result(timeout=30) for future in futures]

    statuses = sorted(response.status for response in responses)
    assert (
        statuses[0] in {200, 202} and statuses[1] == 409
    ), f"two concurrent decisions must yield one success and one 409: {statuses!r}"
    completed = wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"completed", "failed"},
    )
    assert completed["status"] == "completed", completed
    persisted = approval_detail(phase3_client, phase3_org_id, approval_id_value)
    assert persisted.get("decision") == "approved", persisted
    assert persisted.get("approver_user_id") in set(approver_user_ids), persisted
    # One bundled approval may contain multiple actions. Each action is still
    # executed exactly once despite the two racing resume requests.
    assert_each_action_called_once(proposal, mock_adapter_control.calls(run_id))
