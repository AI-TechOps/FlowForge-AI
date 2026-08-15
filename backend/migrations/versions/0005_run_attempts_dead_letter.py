"""Poison-message handling: run attempt counter and dead_letter failure reason.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # How many times a worker has picked this run up. A job that keeps killing
    # its worker is retried forever without this, and each retry costs another
    # worker slot (spec 05 §4).
    op.add_column(
        "runs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    # D18 decision 6: dead-lettering reuses the typed-failure machinery rather
    # than a separate DLQ table, so a poisoned run stays visible on the run
    # detail page beside every other kind of failure.
    op.execute("ALTER TYPE failure_reason ADD VALUE IF NOT EXISTS 'dead_letter'")


def downgrade() -> None:
    op.drop_column("runs", "attempts")
    # Postgres cannot drop a single enum label. Recreating the type would mean
    # rewriting every dependent column, and the value is inert once nothing
    # writes it — so the label is deliberately left behind. Noted rather than
    # silently skipped: a downgrade that claims to be complete and is not is
    # worse than one that says which part it cannot undo.
