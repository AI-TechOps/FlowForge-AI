import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantBase, TimestampMixin


class ApprovalStatus(enum.StrEnum):
    pending = "pending"
    decided = "decided"


class Decision(enum.StrEnum):
    approved = "approved"
    edited = "edited"
    rejected = "rejected"


class RiskClass(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Approval(TenantBase, TimestampMixin, Base):
    """One human decision on one run's proposed actions (D17 decision 2).

    `status` exists separately from `decision` so the one-shot rule can be a
    compare-and-swap on a single column: the endpoint flips pending → decided
    in one UPDATE, and a second request finds nothing to flip (G3.7).
    """

    __tablename__ = "approvals"
    # D17 decision 2 is one bundled approval per run. Enforced here rather
    # than by the unlocked read-then-insert in _pause_for_approval: a
    # redelivered or concurrent initial job could otherwise have both
    # observed "no approval" and inserted, and resume_run's
    # scalar_one_or_none() assumes that cannot happen.
    __table_args__ = (UniqueConstraint("run_id", name="uq_approvals_run"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(
            ApprovalStatus,
            name="approval_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ApprovalStatus.pending,
        nullable=False,
        index=True,
    )
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision: Mapped[Decision | None] = mapped_column(
        Enum(Decision, name="approval_decision", values_callable=lambda e: [m.value for m in e])
    )
    # Both are kept: the audit answer to "what did the agent propose and what
    # did the human actually authorise" needs both sides (G3.4).
    original_proposal: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    final_values: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    feedback: Mapped[str | None] = mapped_column(Text)
    risk_class: Mapped[RiskClass] = mapped_column(
        Enum(RiskClass, name="risk_class", values_callable=lambda e: [m.value for m in e]),
        default=RiskClass.low,
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolExecution(TenantBase, TimestampMixin, Base):
    """Idempotency ledger for write tools (D17 decision 4).

    The unique constraint is the guarantee, not the lookup: two concurrent
    resumes racing the same write both try to insert, exactly one wins, and the
    loser reads the winner's stored result instead of calling the adapter
    again. That holds across process restarts, which a Redis key would not.
    """

    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("run_id", "tool", "args_hash", name="uq_tool_executions_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
