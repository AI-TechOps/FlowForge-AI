"""Record which provider produced an eval batch.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-16

`triage_model` alone is ambiguous: the fake provider still runs under whatever
TRIAGE_MODEL is configured, so a harness batch and a real Ollama batch record
the identical model name while measuring completely different things. The
regression table's whole job is comparability (G5.5), and two rows that look
comparable but are not is the one failure it cannot tolerate.

Backfilled as "unknown" rather than "ollama": the batches recorded before this
column existed genuinely do not say, and guessing would put a fact in the
history that nobody established.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_batches",
        sa.Column("llm_provider", sa.String(20), nullable=False, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_column("eval_batches", "llm_provider")
