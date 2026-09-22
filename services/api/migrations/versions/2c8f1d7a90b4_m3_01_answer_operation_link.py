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
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    question_columns = {
        column["name"]: column for column in inspector.get_columns("question")
    }
    if not question_columns["seed_id"]["nullable"]:
        with op.batch_alter_table("question") as batch_op:
            batch_op.alter_column(
                "seed_id",
                existing_type=sa.String(length=128),
                nullable=True,
            )

    inspector = sa.inspect(connection)
    answer_columns = {
        column["name"]: column for column in inspector.get_columns("answer")
    }
    answer_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("answer")
    }
    answer_foreign_keys = {
        (
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
        )
        for constraint in inspector.get_foreign_keys("answer")
    }
    accepted_column_missing = "accepted_operation_id" not in answer_columns
    accepted_unique_missing = ("accepted_operation_id",) not in answer_uniques
    accepted_foreign_key_missing = (
        ("accepted_operation_id",),
        "operation",
        ("id",),
    ) not in answer_foreign_keys
    if (
        accepted_column_missing
        or accepted_unique_missing
        or accepted_foreign_key_missing
    ):
        with op.batch_alter_table("answer") as batch_op:
            if accepted_column_missing:
                batch_op.add_column(
                    sa.Column(
                        "accepted_operation_id",
                        sa.String(length=128),
                        nullable=True,
                    )
                )
            if accepted_foreign_key_missing:
                batch_op.create_foreign_key(
                    "fk_answer_accepted_operation_id_operation",
                    "operation",
                    ["accepted_operation_id"],
                    ["id"],
                )
            if accepted_unique_missing:
                batch_op.create_unique_constraint(
                    "uq_answer_accepted_operation_id", ["accepted_operation_id"]
                )

    inspector = sa.inspect(connection)
    decision_columns = {
        column["name"]: column for column in inspector.get_columns("decision")
    }
    if not decision_columns["target"]["nullable"]:
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
