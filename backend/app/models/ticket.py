import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantBase, TimestampMixin


class TicketStatus(enum.StrEnum):
    new = "new"
    triaged = "triaged"
    actioned = "actioned"
    closed = "closed"


class Ticket(TenantBase, TimestampMixin, Base):
    """A reported problem. Deliberately minimal (D3): just enough to feed the
    agent and write back to. The requester is a field, not a persona."""

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # The REQUESTER's department (a New Ticket form field) — not the team the
    # ticket is assigned to. Those are different concepts and were conflated
    # once already; assigned_team below is the write target for assign_ticket.
    department: Mapped[str | None] = mapped_column(String(100))
    service: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[str | None] = mapped_column(String(10))
    assigned_team: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(
            TicketStatus,
            name="ticket_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=TicketStatus.new,
        nullable=False,
    )
    external_ref: Mapped[str | None] = mapped_column(String(100))
    is_eval_seed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(320))
    # Append-only list of {author, body, created_at} written by add_internal_note.
    # Not a comment-thread feature (D3 keeps tickets minimal) — just the target
    # the note-writing tool needs so the write is observable and confirmable.
    internal_notes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
