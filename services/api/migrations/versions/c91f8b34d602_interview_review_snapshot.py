"""Freeze interview admission review facts without guessing legacy approvals.

Revision ID: c91f8b34d602
Revises: a7c4e1f29b58
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91f8b34d602"
down_revision: str | Sequence[str] | None = "a7c4e1f29b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("interview")}


def upgrade() -> None:
    # No backfill: old rows have no evidence of their admission-time audit scope.
    if "pack_review_snapshot" not in _columns():
        op.add_column(
            "interview", sa.Column("pack_review_snapshot", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    if "pack_review_snapshot" in _columns():
        with op.batch_alter_table("interview") as batch:
            batch.drop_column("pack_review_snapshot")
