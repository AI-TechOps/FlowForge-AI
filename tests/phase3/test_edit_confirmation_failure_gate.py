from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

from .conftest import (
    MockAdapterControl,
    Phase3Client,
    approval_detail,
    object_body,
    response_detail,
    start_pending_run,
    wait_for_run_status,
)
from .helpers import (
    action_args,
    action_name,
    actions_from,
    approval_id,
    assert_each_action_called_once,
    assert_ticket_reflects_actions,
    audit_entries,
    edited_final_values,
    json_contains,
    original_proposal,
)


def test_g3_4_edits_are_validated_and_original_plus_edited_values_are_audited(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
) -> None:
    del phase3_evidence_ready
    approver_id = approver_user_ids[0]
    marker = uuid4().hex
    _, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"edit-{marker}",
    )
    approval_id_value = approval_id(approval)
    original = original_proposal(approval)

    invalid = phase3_client.decide(
        phase3_org_id,
        approver_id,
        approval_id_value,
        decision="edited",
        final_values={"not_a_write_tool_argument": True},
    )
    assert invalid.status in {400, 422}, response_detail(invalid)
    still_pending = approval_detail(phase3_client, phase3_org_id, approval_id_value)
    assert still_pending.get("decision") in {None, "pending"}, still_pending
    assert mock_adapter_control.calls(run_id) == []

    edited, edited_marker = edited_final_values(original, marker)
    accepted = phase3_client.decide(
        phase3_org_id,
        approver_id,
        approval_id_value,
        decision="edited",
        final_values=edited,
        feedback="Schema-valid edit from G3.4",
    )
    assert accepted.status in {200, 202}, response_detail(accepted)
    completed = wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"completed", "failed"},
    )
    assert completed["status"] == "completed", completed

    persisted = approval_detail(phase3_client, phase3_org_id, approval_id_value)
    assert persisted.get("decision") == "edited", persisted
    assert persisted.get("approver_user_id") == approver_id, persisted
    assert persisted.get("original_proposal") == original, persisted
    assert persisted.get("final_values") == edited, persisted
    entries = audit_entries(completed)
    assert json_contains(entries, original), "audit trail omitted the original proposal"
    assert json_contains(entries, edited), "audit trail omitted the edited final values"
    assert edited_marker in json.dumps(entries), "audit trail omitted the edited value"
    assert_each_action_called_once(edited, mock_adapter_control.calls(run_id))


def test_g3_5_execution_refetches_ticket_and_records_confirmation_in_audit(
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
        marker=f"confirmation-{uuid4().hex}",
    )
    proposal = original_proposal(approval)
    decision = phase3_client.decide(
        phase3_org_id,
        approver_id,
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

    ticket_response = phase3_client.get_ticket(phase3_org_id, ticket_id)
    assert ticket_response.status == 200, response_detail(ticket_response)
    updated_ticket = object_body(ticket_response, "ticket")
    assert_ticket_reflects_actions(updated_ticket, proposal)
    assert_each_action_called_once(proposal, mock_adapter_control.calls(run_id))

    entries = audit_entries(completed)
    confirmation_entries = [
        entry
        for entry in entries
        if "confirm" in str(entry.get("tool", entry.get("name", ""))).lower()
    ]
    assert confirmation_entries, "post-execution confirmation is missing from audit"
    confirmation_json = json.dumps(confirmation_entries, sort_keys=True)
    for action in actions_from(proposal):
        args = action_args(action)
        changed_values = [
            value
            for key, value in args.items()
            if key not in {"ticket_id", "id"} and value is not None
        ]
        assert changed_values, f"write action has no changed value: {action!r}"
        assert any(
            json.dumps(value) in confirmation_json for value in changed_values
        ), (
            f"confirmation audit does not record the applied values for "
            f"{action_name(action)}"
        )


def test_g3_6_persistent_adapter_timeout_retries_then_fails_without_phantom_write(
    phase3_client: Phase3Client,
    phase3_org_id: str,
    approver_user_ids: tuple[str, str],
    phase3_evidence_ready: None,
    mock_adapter_control: MockAdapterControl,
    tool_execution_rows: Callable[[str], list[dict[str, object]]],
) -> None:
    del phase3_evidence_ready
    approver_id = approver_user_ids[0]
    ticket_id, run_id, approval = start_pending_run(
        phase3_client,
        org_id=phase3_org_id,
        marker=f"timeout-{uuid4().hex}",
    )
    approval_id_value = approval_id(approval)
    original = original_proposal(approval)
    before_response = phase3_client.get_ticket(phase3_org_id, ticket_id)
    assert before_response.status == 200, response_detail(before_response)
    ticket_before = object_body(before_response, "ticket")
    mock_adapter_control.inject_timeout(failures=10)

    decision = phase3_client.decide(
        phase3_org_id,
        approver_id,
        approval_id_value,
        decision="approved",
    )
    assert decision.status in {200, 202}, response_detail(decision)
    failed = wait_for_run_status(
        phase3_client,
        org_id=phase3_org_id,
        run_id=run_id,
        statuses={"completed", "failed"},
    )
    assert failed["status"] == "failed", failed

    calls = mock_adapter_control.calls(run_id)
    assert 2 <= len(calls) <= 3, (
        "persistent transport timeout must be retried with a finite max-2 policy; "
        f"adapter calls={calls!r}"
    )
    persisted = approval_detail(phase3_client, phase3_org_id, approval_id_value)
    assert persisted.get("decision") == "approved", persisted
    assert persisted.get("approver_user_id") == approver_id, persisted
    assert original_proposal(persisted) == original
    after_response = phase3_client.get_ticket(phase3_org_id, ticket_id)
    assert after_response.status == 200, response_detail(after_response)
    assert object_body(after_response, "ticket") == ticket_before, (
        "adapter timeout produced a phantom ticket write"
    )
    assert tool_execution_rows(run_id) == [], (
        "failed writes must not persist a successful idempotency result"
    )
