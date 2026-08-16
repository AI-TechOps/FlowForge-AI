"""The ticket system, behind an interface.

Nothing outside this module knows the ticket system is a mock (spec 04 §2).
Swapping in Jira or ServiceNow later is a new `TicketSystemAdapter` subclass
and a factory line — no caller changes, because callers only ever see the
interface and the returned ticket state.

Every method returns the *updated ticket state* rather than None, so the
caller can confirm a write landed without knowing how the backing store works
(G3.5).
"""

import json
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Ticket
from app.tenancy import get_scoped

# Per-ticket fault injection, mirroring the fake provider's directive
# (Phase 2 finding: a process-wide env var cannot be varied by an HTTP-driven
# gate, which must request a failure for one run through the public API).
FAULT_DIRECTIVE = re.compile(r"\[\[FLOWFORGE_TICKET_FAULT:([a-z_]+)\]\]", re.IGNORECASE)


class TicketSystemError(RuntimeError):
    """Transport-shaped failure from the ticket system — retryable."""


class TicketNotFound(LookupError):
    """The ticket does not exist in the acting organization."""


# Test-support state lives in Redis, not in process memory. The gates drive
# the API over HTTP: the *worker* performs adapter calls while the *backend*
# serves the inspection hook, and G3.1 restarts both mid-run. An in-process
# recorder would be invisible across that boundary and empty after a restart.
CALLS_KEY = "flowforge:test:adapter_calls:{run_id}"
FAULT_KEY = "flowforge:test:adapter_fault"
CALLS_TTL_SECONDS = 3600


@dataclass
class CallRecorder:
    """In-process record of adapter calls, for same-process unit tests.

    HTTP-driven gates use the Redis-backed record instead (see `record_call`),
    because it survives both the process boundary and a restart.
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


def _redis() -> Any:
    import redis.asyncio as aioredis

    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def record_call(run_id: uuid.UUID | None, operation: str, args: dict[str, Any]) -> None:
    """Append one adapter call to the durable test record.

    Only active outside prod. Failures here are swallowed: a broken test hook
    must never be able to fail a real write.
    """
    if get_settings().app_env == "prod" or run_id is None:
        return
    client = _redis()
    try:
        key = CALLS_KEY.format(run_id=run_id)
        await client.rpush(key, json.dumps({"tool": operation, "args": args}))
        await client.expire(key, CALLS_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - observability must not break the write path
        pass
    finally:
        await client.aclose()


async def recorded_calls(run_id: uuid.UUID) -> list[dict[str, Any]]:
    client = _redis()
    try:
        raw = await client.lrange(CALLS_KEY.format(run_id=run_id), 0, -1)
    finally:
        await client.aclose()
    return [json.loads(item) for item in raw]


async def set_fault(mode: str, remaining_failures: int) -> None:
    client = _redis()
    try:
        await client.hset(FAULT_KEY, mapping={"mode": mode, "remaining": remaining_failures})
    finally:
        await client.aclose()


async def clear_fault() -> None:
    client = _redis()
    try:
        await client.delete(FAULT_KEY)
    finally:
        await client.aclose()


async def _take_injected_fault() -> str | None:
    """Consume one injected failure, if any remain."""
    if get_settings().app_env == "prod":
        return None
    client = _redis()
    try:
        state = await client.hgetall(FAULT_KEY)
        if not state:
            return None
        remaining = int(state.get("remaining", 0))
        if remaining <= 0:
            return None
        await client.hset(FAULT_KEY, "remaining", remaining - 1)
        return state.get("mode")
    except Exception:  # noqa: BLE001 - a broken hook must not fail real writes
        return None
    finally:
        await client.aclose()


class TicketSystemAdapter(ABC):
    # Whether a *timed-out* write may be retried.
    #
    # A timeout is ambiguous: the remote may have committed and lost the
    # response. Retrying then applies the change twice, and our local ledger
    # cannot prevent it — the ledger guards *our* re-execution, not the remote's
    # state. So retry-on-timeout is opt-in, and the default is the safe answer.
    #
    # An adapter may set this True only if a replayed write is genuinely a
    # no-op remotely: because it is transactional against a store we own (the
    # mock), or because it forwards an idempotency key the remote honours. The
    # `run_id` passed to the adapter is a stable basis for such a key.
    #
    # `TicketSystemError` is different — it means the call did not land — and
    # is always retryable.
    supports_idempotent_retry: bool = False

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

    # Safe: writes are transactional against our own database, so a replayed
    # write converges on the same row rather than applying twice.
    supports_idempotent_retry = True

    def __init__(
        self,
        session: AsyncSession,
        recorder: CallRecorder | None = None,
        run_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.recorder = recorder or CallRecorder()
        self.run_id = run_id

    async def _load(self, ticket_id: uuid.UUID, org_id: uuid.UUID) -> Ticket:
        # Cross-org access is "not found", never "forbidden" — the adapter must
        # not confirm the existence of another tenant's ticket.
        ticket = await get_scoped(self.session, Ticket, ticket_id, org_id)
        if ticket is None:
            raise TicketNotFound(f"ticket {ticket_id} not found")
        await self._maybe_fail(ticket)
        return ticket

    async def _maybe_fail(self, ticket: Ticket) -> None:
        # Precedence: an explicitly injected fault (test hook) beats a
        # per-ticket directive, which beats the process default.
        # Fault injection is a dev/CI facility and must be completely inert in
        # prod. The directive travels in *user-controlled ticket text*, so
        # leaving it live would let anyone who can file a ticket make every
        # approved write against it fail.
        if get_settings().app_env == "prod":
            return

        mode = await _take_injected_fault()
        if mode is None:
            mode = get_settings().mock_ticket_fault
            match = FAULT_DIRECTIVE.search(ticket.description or "")
            if match:
                mode = match.group(1).lower()
        if mode in (None, "none", ""):
            return
        if mode == "timeout":
            # Raise the timeout rather than sleeping past it. The caller's
            # retry policy treats both identically, and sleeping through two
            # 30s tool timeouts would make G3.6 take a minute to prove a
            # property that is really about control flow.
            raise TimeoutError(f"ticket system timed out (injected fault: {mode})")
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
        await record_call(self.run_id, "get_ticket", {"ticket_id": str(ticket_id)})
        return self._state(await self._load(ticket_id, org_id))

    async def assign_ticket(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, team: str
    ) -> dict[str, Any]:
        self.recorder.record("assign_ticket", {"ticket_id": str(ticket_id), "team": team})
        await record_call(self.run_id, "assign_ticket", {"ticket_id": str(ticket_id), "team": team})
        ticket = await self._load(ticket_id, org_id)
        ticket.assigned_team = team
        await self.session.flush()
        return self._state(ticket)

    async def change_priority(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, priority: str
    ) -> dict[str, Any]:
        self.recorder.record("change_priority", {"ticket_id": str(ticket_id), "priority": priority})
        await record_call(
            self.run_id, "change_priority", {"ticket_id": str(ticket_id), "priority": priority}
        )
        ticket = await self._load(ticket_id, org_id)
        ticket.priority = priority
        await self.session.flush()
        return self._state(ticket)

    async def add_note(
        self, ticket_id: uuid.UUID, org_id: uuid.UUID, note: str, author: str
    ) -> dict[str, Any]:
        self.recorder.record("add_note", {"ticket_id": str(ticket_id), "note": note})
        await record_call(self.run_id, "add_note", {"ticket_id": str(ticket_id), "note": note})
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
    session: AsyncSession,
    recorder: CallRecorder | None = None,
    run_id: uuid.UUID | None = None,
) -> TicketSystemAdapter:
    """The one place that decides which adapter is live."""
    return MockTicketSystem(session, recorder, run_id)
