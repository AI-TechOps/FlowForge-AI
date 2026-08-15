import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantBase, TimestampMixin


class RunStatus(enum.StrEnum):
    """Lifecycle from ARCHITECTURE.md. Phase 2 uses queued/running/completed/
    failed; awaiting_approval and executing become active in Phase 3."""

    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    executing = "executing"
    completed = "completed"
    rejected = "rejected"
    failed = "failed"


class FailureReason(enum.StrEnum):
    """Typed failure reasons — the run detail never reports a bare string."""

    ungrounded = "ungrounded"
    schema_invalid = "schema_invalid"
    timeout = "timeout"
    tool_error = "tool_error"
    internal_error = "internal_error"
    # Retried to the limit and still failing (spec 05 §4). Distinct from
    # `internal_error` on purpose: one run that errored is a bug report, a run
    # that poisoned N workers is an operational fact, and they want different
    # responses.
    dead_letter = "dead_letter"


class Run(TenantBase, TimestampMixin, Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status", values_callable=lambda e: [m.value for m in e]),
        default=RunStatus.queued,
        nullable=False,
        index=True,
    )
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Retrieved chunks for this run, kept so the run detail can show evidence
    # even after documents change (citations must stay auditable).
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        Enum(FailureReason, name="failure_reason", values_callable=lambda e: [m.value for m in e])
    )
    error: Mapped[str | None] = mapped_column(Text)
    # Incremented every time a worker picks this run up. The counter lives in
    # Postgres rather than in the queue because it must survive Redis losing
    # the job — which is precisely the situation that re-enqueues it.
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(TenantBase, TimestampMixin, Base):
    """Immutable trail. Every tool call and every LLM call lands here.

    Payload rule (spec 03 §1): never contains secrets. Provider credentials
    live in config and are never tool arguments or logged prompts.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
