"""Evaluation records: one batch, many scored results (spec 06 §1).

The point of storing these rather than printing them is comparability. A batch
is stamped with the `agent_version` that produced it, so two batches at
different versions sit side by side in the regression table with identical
metric keys (G5.5). A score that only ever appears in a terminal cannot answer
"did that prompt change help?".
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantBase, TimestampMixin


class BatchStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"


class EvalBatch(TenantBase, TimestampMixin, Base):
    """One evaluation pass over the seed set.

    `summary` holds the aggregates — per-field accuracy, mean judge scores,
    grounded-rate, hit@k — computed once when the batch finalizes rather than
    recomputed per read, so a recorded batch is a fixed historical fact even if
    the scoring code later changes. That is what makes the regression table
    trustworthy.
    """

    __tablename__ = "eval_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    triage_model: Mapped[str] = mapped_column(String(100), nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="eval_batch_status", values_callable=lambda e: [m.value for m in e]),
        default=BatchStatus.running,
        nullable=False,
        index=True,
    )
    # How many tickets the batch set out to score. Stored so "12 of 20" is
    # answerable while the batch is still running, and so a batch that lost
    # runs is visibly incomplete rather than quietly smaller (G5.4).
    total_tickets: Mapped[int] = mapped_column(nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EvalResult(TenantBase, TimestampMixin, Base):
    """One scored ticket within a batch.

    Both `expected` and `actual` are kept in full. A stored accuracy figure
    with no record of what the model actually said is unarguable-with — and the
    two mis-categorised tickets that prompted G1.5 were only findable because
    the raw outputs were available to compare.
    """

    __tablename__ = "eval_results"
    # One result per ticket per batch: a re-scored batch updates in place
    # rather than accumulating duplicates, which is what makes G5.1's
    # "re-score gives identical accuracy" a meaningful assertion.
    __table_args__ = (
        UniqueConstraint("batch_id", "ticket_id", name="uq_eval_results_batch_ticket"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: a ticket whose run failed outright still gets a result row, so
    # the batch covers 100% of the seed set either way (G5.4).
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    # The fixture's stable identifier (EVAL-001…), carried so a result can be
    # traced back to its label without joining through a ticket row that a
    # reseed may have replaced.
    seed_ref: Mapped[str | None] = mapped_column(String(50), index=True)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actual: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(100))
    # Set when the run never produced a scoreable result. Distinguishes "the
    # agent was wrong" from "the agent never answered", which average very
    # differently.
    failure_reason: Mapped[str | None] = mapped_column(String(50))
