"""Triage schema: tickets, runs, audit_log.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "executing",
    "completed",
    "rejected",
    "failed",
)
FAILURE_REASONS = ("ungrounded", "schema_invalid", "timeout", "tool_error", "internal_error")


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("department", sa.String(100)),
        sa.Column("service", sa.String(100)),
        sa.Column("priority", sa.String(10)),
        sa.Column(
            "status",
            sa.Enum("new", "triaged", "actioned", "closed", name="ticket_status"),
            nullable=False,
            server_default="new",
        ),
        sa.Column("external_ref", sa.String(100)),
        sa.Column("is_eval_seed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(320)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            sa.Enum(*RUN_STATUSES, name="run_status"),
            nullable=False,
            server_default="queued",
            index=True,
        ),
        sa.Column("agent_version", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("output", JSONB()),
        sa.Column("evidence", JSONB()),
        sa.Column("failure_reason", sa.Enum(*FAILURE_REASONS, name="failure_reason")),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "audit_log",
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
            index=True,
        ),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("tool", sa.String(100), nullable=False),
        sa.Column("payload", JSONB()),
        sa.Column("result", JSONB()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        sa.Column("cost_estimate", sa.Float()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("runs")
    op.drop_table("tickets")
    for enum_name in ("failure_reason", "run_status", "ticket_status"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
