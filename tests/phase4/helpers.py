from __future__ import annotations

import json
from collections.abc import Iterable

from .conftest import ApiResponse, response_detail


def assert_allowed(
    responses: ApiResponse | Iterable[ApiResponse],
    *,
    statuses: set[int] | None = None,
) -> None:
    if isinstance(responses, ApiResponse):
        responses = [responses]
    statuses = statuses or {200, 201, 202}
    for response in responses:
        assert response.status in statuses, response_detail(response)


def assert_forbidden(responses: ApiResponse | Iterable[ApiResponse]) -> None:
    if isinstance(responses, ApiResponse):
        responses = [responses]
    for response in responses:
        assert response.status == 403, response_detail(response)


def approval_id(approval: dict[str, object]) -> str:
    value = approval.get("id", approval.get("approval_id"))
    assert isinstance(value, str) and value, f"approval lacks id: {approval!r}"
    return value


def original_proposal(approval: dict[str, object]) -> object:
    for key in ("original_proposal", "proposed_action", "proposed_actions", "proposal"):
        value = approval.get(key)
        if value is not None:
            return value
    raise AssertionError(f"approval lacks its original proposal: {approval!r}")


def actions_from(proposal: object) -> list[dict[str, object]]:
    if isinstance(proposal, list):
        assert all(isinstance(action, dict) for action in proposal), proposal
        return proposal
    assert isinstance(proposal, dict), proposal
    for key in ("actions", "proposed_actions", "tools"):
        value = proposal.get(key)
        if isinstance(value, list):
            assert all(isinstance(action, dict) for action in value), value
            return value
    if any(key in proposal for key in ("tool", "name", "action")):
        return [proposal]
    mapped = [
        {"tool": name, "args": args}
        for name, args in proposal.items()
        if isinstance(args, dict)
        and name in {"assign_ticket", "change_ticket_priority", "add_internal_note"}
    ]
    assert mapped, f"could not locate actions in proposal: {proposal!r}"
    return mapped


def action_args(action: dict[str, object]) -> dict[str, object]:
    for key in ("args", "arguments", "values", "new_values"):
        value = action.get(key)
        if isinstance(value, dict):
            return value
    ignored = {"tool", "name", "action", "requires_approval", "risk_class"}
    values = {key: value for key, value in action.items() if key not in ignored}
    assert values, f"action lacks typed arguments: {action!r}"
    return values


def resource_ids(payload: object) -> set[str]:
    ids: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {
                "id",
                "document_id",
                "ticket_id",
                "run_id",
                "approval_id",
                "chunk_id",
            } and isinstance(value, str):
                ids.add(value)
            ids.update(resource_ids(value))
    elif isinstance(payload, list):
        for value in payload:
            ids.update(resource_ids(value))
    return ids


def assert_not_leaked(response: ApiResponse, *secrets: str) -> None:
    serialized = (
        json.dumps(response.body, sort_keys=True)
        if response.body is not None
        else response.text
    )
    for secret in secrets:
        assert secret not in serialized, (
            f"cross-tenant response leaked {secret!r}: {response_detail(response)}"
        )
