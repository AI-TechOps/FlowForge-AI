"""Approval schema: approvals and tool_executions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "decided", name="approval_status"),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column(
            "approver_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "decision",
            sa.Enum("approved", "edited", "rejected", name="approval_decision"),
        ),
        sa.Column("original_proposal", JSONB(), nullable=False),
        sa.Column("final_values", JSONB()),
        sa.Column("feedback", sa.Text()),
        sa.Column(
            "risk_class",
            sa.Enum("low", "medium", "high", name="risk_class"),
            nullable=False,
            server_default="low",
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tool", sa.String(100), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=False),
        sa.Column("args", JSONB(), nullable=False),
        sa.Column("result", JSONB()),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # The guarantee behind G3.3: a replayed write cannot insert twice.
        sa.UniqueConstraint("run_id", "tool", "args_hash", name="uq_tool_executions_idempotency"),
    )


def downgrade() -> None:
    op.drop_table("tool_executions")
    op.drop_table("approvals")
    for enum_name in ("risk_class", "approval_decision", "approval_status"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
