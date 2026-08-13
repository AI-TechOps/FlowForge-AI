from __future__ import annotations

import copy
import json

WRITE_OPERATION_ALIASES = {
    "assign_ticket": "assign_ticket",
    "change_priority": "change_ticket_priority",
    "change_ticket_priority": "change_ticket_priority",
    "add_note": "add_internal_note",
    "add_internal_note": "add_internal_note",
}


def normalize_operation(name: str) -> str:
    return WRITE_OPERATION_ALIASES.get(name, name)


def approval_id(approval: dict[str, object]) -> str:
    value = approval.get("id", approval.get("approval_id"))
    assert isinstance(value, str) and value, f"approval lacks id: {approval!r}"
    return value


def original_proposal(approval: dict[str, object]) -> object:
    for key in ("original_proposal", "proposed_action", "proposed_actions", "proposal"):
        value = approval.get(key)
        if value is not None:
            return value
    raise AssertionError(f"approval card lacks its original proposal: {approval!r}")


def actions_from(proposal: object) -> list[dict[str, object]]:
    if isinstance(proposal, list):
        assert all(isinstance(action, dict) for action in proposal), proposal
        return proposal
    assert isinstance(proposal, dict), (
        f"proposal must be an object or action list: {proposal!r}"
    )
    for key in ("actions", "proposed_actions", "tools"):
        value = proposal.get(key)
        if isinstance(value, list):
            assert all(isinstance(action, dict) for action in value), value
            return value
    if any(key in proposal for key in ("tool", "name", "action")):
        return [proposal]
    mapped = []
    for name, args in proposal.items():
        if isinstance(args, dict) and name in {
            "assign_ticket",
            "change_ticket_priority",
            "add_internal_note",
        }:
            mapped.append({"tool": name, "args": args})
    assert mapped, f"could not locate proposed actions: {proposal!r}"
    return mapped


def action_name(action: dict[str, object]) -> str:
    value = action.get("tool", action.get("name", action.get("action")))
    assert isinstance(value, str) and value, (
        f"proposed action lacks tool name: {action!r}"
    )
    return normalize_operation(value)


def action_args(action: dict[str, object]) -> dict[str, object]:
    for key in ("args", "arguments", "values", "new_values"):
        value = action.get(key)
        if isinstance(value, dict):
            return value
    ignored = {"tool", "name", "action", "requires_approval", "risk_class"}
    values = {key: value for key, value in action.items() if key not in ignored}
    assert values, f"proposed action lacks typed arguments: {action!r}"
    return values


def call_name(call: dict[str, object]) -> str:
    value = call.get(
        "tool", call.get("operation", call.get("name", call.get("method")))
    )
    assert isinstance(value, str) and value, (
        f"recorder entry lacks operation name: {call!r}"
    )
    return normalize_operation(value)


def assert_each_action_called_once(
    proposal: object, calls: list[dict[str, object]]
) -> None:
    expected = [action_name(action) for action in actions_from(proposal)]
    observed = [call_name(call) for call in calls]
    assert len(observed) == len(expected), (
        f"one bundled decision must execute each proposed action once; "
        f"expected={expected!r}, observed={observed!r}"
    )
    for name in expected:
        assert observed.count(name) == expected.count(name), (
            f"adapter call count differs for {name}: expected={expected!r}, observed={observed!r}"
        )


def edited_final_values(proposal: object, marker: str) -> tuple[object, str]:
    edited = copy.deepcopy(proposal)
    actions = actions_from(edited)
    preferred = sorted(
        actions,
        key=lambda action: action_name(action) != "add_internal_note",
    )
    action = preferred[0]
    name = action_name(action)
    args = next(
        (
            value
            for key in ("args", "arguments", "values", "new_values")
            if isinstance((value := action.get(key)), dict)
        ),
        action,
    )

    if name == "add_internal_note":
        key = (
            "note"
            if "note" in args
            else next((key for key in args if "note" in key.lower()), "note")
        )
        value = f"Phase 3 approved edit {marker}"
        args[key] = value
        return edited, value
    if name == "change_ticket_priority":
        key = "priority" if "priority" in args else "new_priority"
        current = str(args.get(key, "P3"))
        value = next(
            priority for priority in ("P1", "P2", "P3", "P4") if priority != current
        )
        args[key] = value
        return edited, value
    if name == "assign_ticket":
        key = "team" if "team" in args else "assigned_team"
        current = str(args.get(key, "Service Desk"))
        value = next(
            team
            for team in ("Service Desk", "IT Infrastructure", "IT Security")
            if team != current
        )
        args[key] = value
        return edited, value
    raise AssertionError(f"unexpected Phase 3 write tool {name!r}")


def approval_card_contract(approval: dict[str, object]) -> None:
    required_concepts = {
        "affected ticket": ("ticket", "affected_ticket"),
        "new values/proposal": (
            "new_values",
            "original_proposal",
            "proposed_action",
            "proposed_actions",
        ),
        "existing values": ("existing_values", "current_values"),
        "evidence": ("evidence", "evidence_used"),
        "confidence": ("confidence",),
        "risk classification": ("risk_class", "risk_classification"),
        "agent version": ("agent_version",),
    }
    missing = [
        concept
        for concept, keys in required_concepts.items()
        if not any(key in approval for key in keys)
    ]
    assert not missing, f"approval card is missing {missing!r}: {approval!r}"


def assert_ticket_reflects_actions(ticket: dict[str, object], proposal: object) -> None:
    serialized = json.dumps(ticket, sort_keys=True)
    for action in actions_from(proposal):
        name = action_name(action)
        args = action_args(action)
        if name == "change_ticket_priority":
            expected = args.get("priority", args.get("new_priority"))
            assert ticket.get("priority") == expected, (ticket, action)
        elif name == "assign_ticket":
            expected = args.get("team", args.get("assigned_team"))
            actual = ticket.get("assigned_team", ticket.get("team"))
            assert actual == expected, (ticket, action)
        elif name == "add_internal_note":
            expected = args.get("note", args.get("internal_note"))
            assert isinstance(expected, str) and expected in serialized, (
                ticket,
                action,
            )
        else:
            raise AssertionError(f"unexpected Phase 3 write tool {name!r}")


def audit_entries(run: dict[str, object]) -> list[dict[str, object]]:
    value = run.get("audit_entries", run.get("audit_log"))
    assert isinstance(value, list) and all(isinstance(item, dict) for item in value), (
        run
    )
    return value


def decision_snapshot(approval: dict[str, object]) -> tuple[object, ...]:
    return tuple(
        approval.get(key)
        for key in (
            "decision",
            "approver_user_id",
            "final_values",
            "feedback",
            "decided_at",
        )
    )


def json_contains(container: object, value: object) -> bool:
    if container == value:
        return True
    if isinstance(container, dict):
        return any(json_contains(item, value) for item in container.values())
    if isinstance(container, list):
        return any(json_contains(item, value) for item in container)
    return False
