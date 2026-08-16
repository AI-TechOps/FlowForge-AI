"""Attribution: which human triggered a run.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Job payloads now carry the acting user (spec 05 §4), but a queue message
    # is not a record. Recovery re-enqueues a run long after the request is
    # gone, and without this column the human who started the work is
    # unrecoverable — the audit trail could show every tool call and still not
    # answer who set it in motion.
    #
    # SET NULL rather than CASCADE: deleting a user must not delete the runs
    # they triggered. The run happened; the audit trail says so.
    op.add_column(
        "runs",
        sa.Column(
            "triggered_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "triggered_by")
