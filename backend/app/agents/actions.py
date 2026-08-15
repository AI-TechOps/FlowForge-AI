"""Turning a classification into concrete, approvable write actions.

`TriageResult` names *values* — a team, a priority, a resolution — and never
names a tool. This module is the deterministic bridge from those values to the
tool calls a human will authorise (D17 decision 1). Keeping it here, in code,
means the model classifies and code decides control flow: exactly the property
D16 decision 2 bought, extended to the write path.

Everything below is a pure function of (triage result, current ticket), so the
whole proposal step is testable without a model or a database.
"""

from dataclasses import dataclass, field
from typing import Any

from app.agents.schema import TriageResult
from app.agents.taxonomy import Priority
from app.models import RiskClass

# Ordered worst-to-best so "is this a raise?" is an index comparison.
_PRIORITY_RANK = {Priority.p4: 0, Priority.p3: 1, Priority.p2: 2, Priority.p1: 3}


@dataclass(frozen=True)
class ProposedAction:
    tool: str
    args: dict[str, Any]
    # What the field looks like now, so the approval card can show
    # "IT Support → IT Infrastructure" rather than just the new value.
    field_name: str
    current_value: Any
    new_value: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "field": self.field_name,
            "current_value": self.current_value,
            "new_value": self.new_value,
        }


@dataclass
class Proposal:
    actions: list[ProposedAction] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.actions

    def as_list(self) -> list[dict[str, Any]]:
        return [action.as_dict() for action in self.actions]


def derive_actions(result: TriageResult, ticket: dict[str, Any]) -> Proposal:
    """Map a validated triage result onto the write tools.

    An action is proposed only when it would actually change the ticket:
    proposing "set priority to P3" on a ticket already at P3 is noise on the
    approval card and an audit record of a write that changed nothing.

    The internal note is always proposed — it records the agent's reasoning on
    the ticket, which is new information even when nothing else moves.
    """
    ticket_id = str(ticket.get("id"))
    actions: list[ProposedAction] = []

    # assigned_team, NOT department: department is the requester's org unit.
    current_team = ticket.get("assigned_team")
    if result.recommended_team.value != current_team:
        actions.append(
            ProposedAction(
                tool="assign_ticket",
                args={"ticket_id": ticket_id, "team": result.recommended_team.value},
                field_name="assigned_team",
                current_value=current_team,
                new_value=result.recommended_team.value,
            )
        )

    current_priority = ticket.get("priority")
    if result.suggested_priority.value != current_priority:
        actions.append(
            ProposedAction(
                tool="change_ticket_priority",
                args={"ticket_id": ticket_id, "priority": result.suggested_priority.value},
                field_name="priority",
                current_value=current_priority,
                new_value=result.suggested_priority.value,
            )
        )

    actions.append(
        ProposedAction(
            tool="add_internal_note",
            args={"ticket_id": ticket_id, "note": result.recommended_resolution},
            field_name="internal_note",
            current_value=None,
            new_value=result.recommended_resolution,
        )
    )
    return Proposal(actions=actions)


def classify_risk(proposal: Proposal, ticket: dict[str, Any]) -> RiskClass:
    """Rule-based risk for the approval card (spec 04 §6).

    Deliberately rules, not a model: the approver needs a signal they can
    predict and argue with, and "why was this high risk?" must have an answer
    that is not "the model said so".
    """
    current_priority = ticket.get("priority")
    current_rank = _PRIORITY_RANK.get(_as_priority(current_priority), -1)

    highest = RiskClass.low
    for action in proposal.actions:
        if action.tool == "change_ticket_priority":
            new_rank = _PRIORITY_RANK.get(_as_priority(action.new_value), -1)
            if action.new_value == Priority.p1.value:
                # Paging a team out of hours is the most expensive mistake
                # this agent can propose.
                return RiskClass.high
            if new_rank > current_rank:
                highest = _max_risk(highest, RiskClass.medium)
        elif action.tool == "assign_ticket":
            # Routing to the wrong team delays a ticket; it does not page
            # anyone or lose data.
            highest = _max_risk(highest, RiskClass.medium)
    return highest


def _as_priority(value: Any) -> Priority | None:
    try:
        return Priority(value)
    except ValueError:
        return None


def _max_risk(left: RiskClass, right: RiskClass) -> RiskClass:
    order = {RiskClass.low: 0, RiskClass.medium: 1, RiskClass.high: 2}
    return left if order[left] >= order[right] else right
