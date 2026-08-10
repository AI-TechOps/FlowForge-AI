"""The ticket system, behind an interface.

Nothing outside this module knows the ticket system is a mock (spec 04 §2).
Swapping in Jira or ServiceNow later is a new `TicketSystemAdapter` subclass
and a factory line — no caller changes, because callers only ever see the
interface and the returned ticket state.

Every method returns the *updated ticket state* rather than None, so the
caller can confirm a write landed without knowing how the backing store works
(G3.5).
"""

import asyncio
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Ticket

# Per-ticket fault injection, mirroring the fake provider's directive
# (Phase 2 finding: a process-wide env var cannot be varied by an HTTP-driven
# gate, which must request a failure for one run through the public API).
FAULT_DIRECTIVE = re.compile(r"\[\[FLOWFORGE_TICKET_FAULT:([a-z_]+)\]\]", re.IGNORECASE)


class TicketSystemError(RuntimeError):
    """Transport-shaped failure from the ticket system — retryable."""


class TicketNotFound(LookupError):
    """The ticket does not exist in the acting organization."""


@dataclass
class CallRecorder:
    """In-process record of adapter calls.

    Useful for unit tests running in the same process. HTTP-driven gates
    should assert on the durable evidence instead — `tool_executions` rows and
    `audit_log` entries — because those survive the process boundary.
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def record(self, method: str, args: dict[str, Any]) -> None:
        self.calls.append((method, args))

    def count(self, method: str | None = None) -> int:
        if method is None:
            return len(self.calls)
        return sum(1 for name, _ in self.calls if name == method)

    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [c for c in self.calls if c[0] != "get_ticket"]


class TicketSystemAdapter(ABC):
    @abstractmethod
    async def get_ticket(self, ticket_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]: ...

    @abstractmethod
    async def assign_ticket(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, team: str
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def change_priority(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, priority: str
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def add_note(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, note: str, author: str
    ) -> dict[str, Any]: ...


class MockTicketSystem(TicketSystemAdapter):
    """Mock backed by our own `tickets` table plus `external_ref`.

    Deliberately writes through the same rows the rest of the app reads, so a
    confirmation re-fetch observes exactly what an external system would have
    changed. A real adapter would call an API instead; the contract is the same.
    """

    def __init__(self, session: AsyncSession, recorder: CallRecorder | None = None) -> None:
        self.session = session
        self.recorder = recorder or CallRecorder()

    async def _load(self, ticket_id: uuid.UUID, org_id: uuid.UUID) -> Ticket:
        ticket = await self.session.get(Ticket, ticket_id)
        # Cross-org access is "not found", never "forbidden" — the adapter must
        # not confirm the existence of another tenant's ticket.
        if ticket is None or ticket.org_id != org_id:
            raise TicketNotFound(f"ticket {ticket_id} not found")
        await self._maybe_fail(ticket)
        return ticket

    async def _maybe_fail(self, ticket: Ticket) -> None:
        mode = get_settings().mock_ticket_fault
        match = FAULT_DIRECTIVE.search(ticket.description or "")
        if match:
            mode = match.group(1).lower()
        if mode in ("none", ""):
            return
        if mode == "timeout":
            # Long enough that the tool's own timeout fires; the point is to
            # exercise the retry path, not to actually wait.
            await asyncio.sleep(get_settings().tool_timeout_seconds + 5)
        raise TicketSystemError(f"ticket system unavailable (injected fault: {mode})")

    @staticmethod
    def _state(ticket: Ticket) -> dict[str, Any]:
        return {
            "id": str(ticket.id),
            "title": ticket.title,
            "status": ticket.status.value,
            "priority": ticket.priority,
            "assigned_team": ticket.assigned_team,
            "internal_notes": list(ticket.internal_notes or []),
            "external_ref": ticket.external_ref,
        }

    async def get_ticket(self, ticket_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
        self.recorder.record("get_ticket", {"ticket_id": str(ticket_id)})
        return self._state(await self._load(ticket_id, org_id))

    async def assign_ticket(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, team: str
    ) -> dict[str, Any]:
        self.recorder.record("assign_ticket", {"ticket_id": str(ticket_id), "team": team})
        ticket = await self._load(ticket_id, org_id)
        ticket.assigned_team = team
        await self.session.flush()
        return self._state(ticket)

    async def change_priority(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, priority: str
    ) -> dict[str, Any]:
        self.recorder.record("change_priority", {"ticket_id": str(ticket_id), "priority": priority})
        ticket = await self._load(ticket_id, org_id)
        ticket.priority = priority
        await self.session.flush()
        return self._state(ticket)

    async def add_note(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, note: str, author: str
    ) -> dict[str, Any]:
        self.recorder.record("add_note", {"ticket_id": str(ticket_id), "note": note})
        ticket = await self._load(ticket_id, org_id)
        # Reassign rather than append: SQLAlchemy does not track in-place
        # mutation of a JSONB list, so appending would silently not persist.
        ticket.internal_notes = [
            *(ticket.internal_notes or []),
            {"author": author, "body": note, "created_at": datetime.now(UTC).isoformat()},
        ]
        await self.session.flush()
        return self._state(ticket)


def get_ticket_system(
    session: AsyncSession, recorder: CallRecorder | None = None
) -> TicketSystemAdapter:
    """The one place that decides which adapter is live."""
    return MockTicketSystem(session, recorder)
