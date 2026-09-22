"""M4-02 persist grounded coaching state and resume drafts.

Revision ID: b4d7c2e91f30
Revises: 7f1b9c4d2a60
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d7c2e91f30"
down_revision: str | Sequence[str] | None = "7f1b9c4d2a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    report_columns = {
        column["name"]: column for column in inspector.get_columns("report")
    }
    report_foreign_keys = {
        (
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
        )
        for constraint in inspector.get_foreign_keys("report")
    }
    missing_columns = {
        "improvements_status",
        "active_operation_id",
        "improvements_operation_id",
    } - set(report_columns)
    improvements_foreign_key_missing = (
        ("improvements_operation_id",),
        "operation",
        ("id",),
    ) not in report_foreign_keys
    if missing_columns or improvements_foreign_key_missing:
        with op.batch_alter_table("report") as batch_op:
            if "improvements_status" in missing_columns:
                batch_op.add_column(
                    sa.Column(
                        "improvements_status",
                        sa.String(length=24),
                        nullable=False,
                        server_default="not_requested",
                    )
                )
            if "active_operation_id" in missing_columns:
                batch_op.add_column(
                    sa.Column(
                        "active_operation_id", sa.String(length=128), nullable=True
                    )
                )
            if "improvements_operation_id" in missing_columns:
                batch_op.add_column(
                    sa.Column(
                        "improvements_operation_id",
                        sa.String(length=128),
                        nullable=True,
                    )
                )
            if improvements_foreign_key_missing:
                batch_op.create_foreign_key(
                    "fk_report_improvements_operation",
                    "operation",
                    ["improvements_operation_id"],
                    ["id"],
                )
            if "improvements_status" in missing_columns:
                batch_op.alter_column("improvements_status", server_default=None)

    if "resume_draft" in sa.inspect(connection).get_table_names():
        return
    op.create_table(
        "resume_draft",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("profile_snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("interview_id", sa.String(length=128), nullable=True),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("missing_facts", sa.JSON(), nullable=False),
        sa.Column("cautions", sa.JSON(), nullable=False),
        sa.Column("target_context", sa.JSON(), nullable=False),
        sa.Column("active_operation_id", sa.String(length=128), nullable=True),
        sa.Column("generation_operation_id", sa.String(length=128), nullable=True),
        sa.Column("run_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"]),
        sa.ForeignKeyConstraint(["profile_snapshot_id"], ["profile_snapshot.id"]),
        sa.ForeignKeyConstraint(["interview_id"], ["interview.id"]),
        sa.ForeignKeyConstraint(["generation_operation_id"], ["operation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_snapshot_id",
            "target_hash",
            name="uq_resume_draft_snapshot_target",
        ),
    )


def downgrade() -> None:
    op.drop_table("resume_draft")
    with op.batch_alter_table("report") as batch_op:
        batch_op.drop_constraint("fk_report_improvements_operation", type_="foreignkey")
        batch_op.drop_column("improvements_operation_id")
        batch_op.drop_column("active_operation_id")
        batch_op.drop_column("improvements_status")
