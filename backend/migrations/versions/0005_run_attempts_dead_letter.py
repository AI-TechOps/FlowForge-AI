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
    # Postgres cannot drop a single enum label, so the type is rebuilt without
    # it. Leaving the label behind was the first version of this and it left
    # the schema not equivalent to 0004 — which is what task 9 asked for, and
    # what the migration cycle gate is supposed to prove. An inert leftover is
    # still a difference, and "mostly reversible" is not a property worth
    # claiming.
    #
    # Any row already carrying the value has to go somewhere first;
    # internal_error is the honest home for "it failed and we stopped trying".
    op.execute(
        "UPDATE runs SET failure_reason = 'internal_error' WHERE failure_reason = 'dead_letter'"
    )
    op.execute("ALTER TYPE failure_reason RENAME TO failure_reason_old")
    op.execute(
        "CREATE TYPE failure_reason AS ENUM "
        "('ungrounded', 'schema_invalid', 'timeout', 'tool_error', 'internal_error')"
    )
    op.execute(
        "ALTER TABLE runs ALTER COLUMN failure_reason "
        "TYPE failure_reason USING failure_reason::text::failure_reason"
    )
    op.execute("DROP TYPE failure_reason_old")
