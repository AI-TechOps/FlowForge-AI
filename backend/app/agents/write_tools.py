"""The three approval-gated write tools.

Each carries the full write-tool contract (CLAUDE.md, spec 04 §3): org and
user context, typed arguments, permission check, idempotency key, timeout,
audit record, retry policy, mock implementation, and post-execution
confirmation.

Two properties are worth stating plainly, because they are what make the
approval gate meaningful rather than decorative:

- **Retry is transport-only.** A write that we know landed is never retried.
  The retry loop is entered only for `TicketSystemError`, and the idempotency
  ledger is claimed *before* the adapter is called, so even a retry that races
  a slow-but-successful write cannot double-apply it (G3.3, G3.6).
- **Confirmation is a separate read.** After executing, we re-fetch the ticket
  through the adapter and assert the field actually holds the new value. A
  write that reports success but did not land fails the run (G3.5).
"""

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents import audit
from app.agents.taxonomy import Priority, Team
from app.agents.tools import Tool, ToolContext, ToolPermissionError, register
from app.config import get_settings
from app.integrations.ticket_system import (
    TicketNotFound,
    TicketSystemError,
    get_ticket_system,
)
from app.models import ToolExecution

MAX_WRITE_ATTEMPTS = 2
WRITE_BACKOFF_SECONDS = 1.0


class WriteToolError(RuntimeError):
    """A write tool could not complete. The run fails; no phantom write."""


class AssignTicketArgs(BaseModel):
    ticket_id: uuid.UUID
    team: Team


class ChangePriorityArgs(BaseModel):
    ticket_id: uuid.UUID
    priority: Priority


class AddNoteArgs(BaseModel):
    ticket_id: uuid.UUID
    note: str = Field(min_length=1, max_length=5000)


def args_hash(tool: str, args: dict[str, Any]) -> str:
    """Stable hash over tool + arguments — half of the idempotency key."""
    payload = json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class _Confirmation:
    field_name: str
    expected: Any


async def _execute_once(
    context: ToolContext,
    tool_name: str,
    args: dict[str, Any],
    confirmation: _Confirmation,
) -> dict[str, Any]:
    """Claim idempotency, execute with timeout+retry, then confirm."""
    if context.run_id is None:
        raise WriteToolError("write tools require a run context")

    # The ledger column is JSONB, so it needs plain JSON types — a UUID object
    # raises "not JSON serializable" at flush. Keep `args` typed for dispatch
    # (the adapter wants a real UUID) and persist a JSON-safe copy.
    json_args = {
        key: (str(value) if isinstance(value, uuid.UUID) else value) for key, value in args.items()
    }
    digest = args_hash(tool_name, json_args)
    existing = (
        await context.session.execute(
            select(ToolExecution).where(
                ToolExecution.run_id == context.run_id,
                ToolExecution.tool == tool_name,
                ToolExecution.args_hash == digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Already done in a previous attempt or a concurrent resume. Return the
        # stored result; the adapter is not touched (G3.3).
        return {"result": existing.result, "idempotent_replay": True}

    ledger = ToolExecution(
        org_id=context.org_id,
        run_id=context.run_id,
        tool=tool_name,
        args_hash=digest,
        args=json_args,
    )
    context.session.add(ledger)
    try:
        # Claim the key before calling out. If a concurrent resume claimed it
        # first, the unique constraint rejects us here — before any write.
        await context.session.flush()
    except IntegrityError:
        await context.session.rollback()
        winner = (
            await context.session.execute(
                select(ToolExecution).where(
                    ToolExecution.run_id == context.run_id,
                    ToolExecution.tool == tool_name,
                    ToolExecution.args_hash == digest,
                )
            )
        ).scalar_one()
        return {"result": winner.result, "idempotent_replay": True}

    adapter = get_ticket_system(context.session, run_id=context.run_id)
    settings = get_settings()
    last_error: Exception | None = None

    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        try:
            async with asyncio.timeout(settings.tool_timeout_seconds):
                state = await _dispatch(adapter, tool_name, context, args)
            break
        except (TicketSystemError, TimeoutError) as exc:
            # Transport-shaped only. A confirmed write never reaches here.
            last_error = exc
            # A timeout is ambiguous — the remote may have committed and lost
            # the response. Our ledger guards *our* re-execution, not the
            # remote's state, so retrying can still double-apply. Only retry a
            # timeout against an adapter that says a replay is safe.
            ambiguous = isinstance(exc, TimeoutError) and not getattr(
                adapter, "supports_idempotent_retry", False
            )
            if ambiguous:
                raise WriteToolError(
                    f"{tool_name} timed out with an indeterminate outcome and "
                    f"{type(adapter).__name__} does not support safe replay; "
                    f"not retrying: {exc}"
                ) from exc
            if attempt == MAX_WRITE_ATTEMPTS:
                raise WriteToolError(f"{tool_name} failed after {attempt} attempts: {exc}") from exc
            await asyncio.sleep(WRITE_BACKOFF_SECONDS * attempt)
        except TicketNotFound as exc:
            raise WriteToolError(str(exc)) from exc
    else:  # pragma: no cover - loop always breaks or raises
        raise WriteToolError(f"{tool_name} failed: {last_error}")

    confirmed_state = await adapter.get_ticket(args["ticket_id"], context.org_id)
    actual = confirmed_state.get(confirmation.field_name)
    landed = (
        confirmation.expected in [n.get("body") for n in (actual or [])]
        if confirmation.field_name == "internal_notes"
        else actual == confirmation.expected
    )
    if not landed:
        raise WriteToolError(
            f"{tool_name} reported success but {confirmation.field_name} is {actual!r}, "
            f"expected {confirmation.expected!r}"
        )

    ledger.result = state
    ledger.confirmed = True
    await context.session.flush()

    # Record the confirmation as its own audit entry (spec 04 §3). The write
    # and the proof the write landed are separate facts: an audit trail that
    # only says "we called assign_ticket" cannot answer "did it take effect?".
    await audit.record(
        org_id=context.org_id,
        run_id=context.run_id,
        actor=context.actor,
        tool=f"{tool_name}.confirm",
        payload={"expected": {confirmation.field_name: confirmation.expected}},
        result={"confirmed": True, "ticket": confirmed_state},
    )
    return {"result": state, "confirmed": True, "idempotent_replay": False}


async def _dispatch(
    adapter: Any, tool_name: str, context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    ticket_id = args["ticket_id"]
    if tool_name == "assign_ticket":
        return await adapter.assign_ticket(ticket_id, context.org_id, args["team"])
    if tool_name == "change_ticket_priority":
        return await adapter.change_priority(ticket_id, context.org_id, args["priority"])
    if tool_name == "add_internal_note":
        return await adapter.add_note(ticket_id, context.org_id, args["note"], context.actor)
    raise WriteToolError(f"unknown write tool: {tool_name}")


async def _assign_ticket(context: ToolContext, args: AssignTicketArgs) -> dict[str, Any]:
    return await _execute_once(
        context,
        "assign_ticket",
        {"ticket_id": args.ticket_id, "team": args.team.value},
        _Confirmation("assigned_team", args.team.value),
    )


async def _change_ticket_priority(context: ToolContext, args: ChangePriorityArgs) -> dict[str, Any]:
    return await _execute_once(
        context,
        "change_ticket_priority",
        {"ticket_id": args.ticket_id, "priority": args.priority.value},
        _Confirmation("priority", args.priority.value),
    )


async def _add_internal_note(context: ToolContext, args: AddNoteArgs) -> dict[str, Any]:
    return await _execute_once(
        context,
        "add_internal_note",
        {"ticket_id": args.ticket_id, "note": args.note},
        _Confirmation("internal_notes", args.note),
    )


def require_granted_approval(context: ToolContext, args: BaseModel) -> None:
    """Refuse a gated write unless a human decision authorised this run.

    `requires_approval=True` was previously passive metadata — `Tool.invoke`
    only runs a non-null `permission_check` — so any caller holding a
    ToolContext could execute a write directly. The graph happens to reach
    these tools only after the interrupt, but "happens to" is not a control.

    Fail-closed: the flag is set solely by the resume path after it loads a
    decided approval, so a new caller gets a refusal rather than a write.
    """
    del args
    if not context.approval_granted:
        raise ToolPermissionError(
            "write tools require an approved human decision for this run; "
            "the acting context carries no granted approval"
        )


assign_ticket = Tool(
    name="assign_ticket",
    description="Assign the ticket to a team. Requires human approval.",
    args_model=AssignTicketArgs,
    handler=_assign_ticket,
    requires_approval=True,
    permission_check=require_granted_approval,
)

change_ticket_priority = Tool(
    name="change_ticket_priority",
    description="Change the ticket's priority. Requires human approval.",
    args_model=ChangePriorityArgs,
    handler=_change_ticket_priority,
    requires_approval=True,
    permission_check=require_granted_approval,
)

add_internal_note = Tool(
    name="add_internal_note",
    description="Add an internal note to the ticket. Requires human approval.",
    args_model=AddNoteArgs,
    handler=_add_internal_note,
    requires_approval=True,
    permission_check=require_granted_approval,
)

WRITE_TOOLS = {
    assign_ticket.name: assign_ticket,
    change_ticket_priority.name: change_ticket_priority,
    add_internal_note.name: add_internal_note,
}


__all__ = [
    "WRITE_TOOLS",
    "WriteToolError",
    "add_internal_note",
    "args_hash",
    "assign_ticket",
    "change_ticket_priority",
]


# Registered at import so the graph and the approval resume path can look them
# up by name through the same registry the read tools use.
for _tool in WRITE_TOOLS.values():
    register(_tool)
