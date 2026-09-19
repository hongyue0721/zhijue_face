"""M3-01 answer operation recovery and experience-question fallback.

Revision ID: 2c8f1d7a90b4
Revises: 18e3af0d1942
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c8f1d7a90b4"
down_revision: str | Sequence[str] | None = "18e3af0d1942"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Link an accepted answer to its original operation and allow bounded non-seed roots."""
    with op.batch_alter_table("question") as batch_op:
        batch_op.alter_column(
            "seed_id",
            existing_type=sa.String(length=128),
            nullable=True,
        )

    with op.batch_alter_table("answer") as batch_op:
        batch_op.add_column(
            sa.Column("accepted_operation_id", sa.String(length=128), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_answer_accepted_operation_id_operation",
            "operation",
            ["accepted_operation_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_answer_accepted_operation_id", ["accepted_operation_id"]
        )

    with op.batch_alter_table("decision") as batch_op:
        batch_op.alter_column(
            "target",
            existing_type=sa.JSON(),
            nullable=True,
        )


def downgrade() -> None:
    """Restore the M1 schema without discarding existing seed-backed questions."""
    with op.batch_alter_table("answer") as batch_op:
        batch_op.drop_constraint("uq_answer_accepted_operation_id", type_="unique")
        batch_op.drop_constraint(
            "fk_answer_accepted_operation_id_operation", type_="foreignkey"
        )
        batch_op.drop_column("accepted_operation_id")

    with op.batch_alter_table("question") as batch_op:
        batch_op.alter_column(
            "seed_id",
            existing_type=sa.String(length=128),
            nullable=False,
        )

    with op.batch_alter_table("decision") as batch_op:
        batch_op.alter_column(
            "target",
            existing_type=sa.JSON(),
            nullable=False,
        )
