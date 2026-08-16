"""Evaluation records: eval_batches and eval_results.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Stamped per batch, not read from config at display time: the whole
        # point of the regression table is comparing versions, which only works
        # if each row remembers the version that produced it (G5.5).
        sa.Column("agent_version", sa.String(50), nullable=False),
        sa.Column("triage_model", sa.String(100), nullable=False),
        sa.Column("judge_model", sa.String(100)),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="eval_batch_status"),
            nullable=False,
            server_default="running",
            index=True,
        ),
        sa.Column("total_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("summary", JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "eval_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("eval_batches.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # SET NULL, not CASCADE: deleting a run must not silently shrink a
        # recorded batch. The score stays; only the link to the run is lost.
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seed_ref", sa.String(50), index=True),
        sa.Column("expected", JSONB(), nullable=False),
        sa.Column("actual", JSONB()),
        sa.Column("scores", JSONB(), nullable=False),
        sa.Column("judge_model", sa.String(100)),
        sa.Column("failure_reason", sa.String(50)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Re-scoring a batch updates in place instead of accumulating
        # duplicates, which is what makes G5.1's "same batch re-scored gives
        # identical accuracy" a statement about determinism rather than about
        # how many rows happen to exist.
        sa.UniqueConstraint("batch_id", "ticket_id", name="uq_eval_results_batch_ticket"),
    )


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_batches")
    sa.Enum(name="eval_batch_status").drop(op.get_bind(), checkfirst=True)
