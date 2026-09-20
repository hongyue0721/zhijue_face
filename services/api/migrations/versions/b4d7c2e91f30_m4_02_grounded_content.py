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
    with op.batch_alter_table("report") as batch_op:
        batch_op.add_column(
            sa.Column(
                "improvements_status",
                sa.String(length=24),
                nullable=False,
                server_default="not_requested",
            )
        )
        batch_op.add_column(
            sa.Column("active_operation_id", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("improvements_operation_id", sa.String(length=128), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_report_improvements_operation",
            "operation",
            ["improvements_operation_id"],
            ["id"],
        )
        batch_op.alter_column("improvements_status", server_default=None)

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
