"""Add immutable knowledge pack releases, reviews, import receipts and
interview pack-binding columns.

Revision ID: a7c4e1f29b58
Revises: e62a9f8c10bd
Create Date: 2026-09-25

幂等补齐风格与 e62a9f8c10bd 一致：可重复执行，不破坏既有行；旧 Interview
行的三个新列允许 NULL（读取路径视为 legacy_unresolved，不回填猜测值）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c4e1f29b58"
down_revision: str | Sequence[str] | None = "e62a9f8c10bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "knowledge_pack_release" not in tables:
        op.create_table(
            "knowledge_pack_release",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("pack_id", sa.String(length=64), nullable=False),
            sa.Column("version", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.String(length=800), nullable=False),
            sa.Column("format_version", sa.String(length=16), nullable=False),
            sa.Column("competency_profile_id", sa.String(length=64), nullable=False),
            sa.Column("content_digest", sa.String(length=80), nullable=False),
            sa.Column("upload_sha256", sa.String(length=64), nullable=False),
            sa.Column("storage_kind", sa.String(length=16), nullable=False),
            sa.Column("storage_root", sa.String(length=300), nullable=False),
            sa.Column("manifest_snapshot", sa.JSON(), nullable=False),
            sa.Column("file_index", sa.JSON(), nullable=False),
            sa.Column("validation_status", sa.String(length=16), nullable=False),
            sa.Column("validation_checks", sa.JSON(), nullable=False),
            sa.Column("seed_count", sa.Integer(), nullable=False),
            sa.Column("approved_seed_count", sa.Integer(), nullable=False),
            sa.Column("source_count", sa.Integer(), nullable=False),
            sa.Column("supported_scope", sa.String(length=640), nullable=False),
            sa.Column("unsupported_scope", sa.String(length=640), nullable=False),
            sa.Column("source_kind", sa.String(length=48), nullable=False),
            sa.Column("import_operation_id", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("pack_id", "version"),
        )
    if "knowledge_pack_review" not in tables:
        op.create_table(
            "knowledge_pack_review",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("release_id", sa.String(length=64), nullable=False),
            sa.Column("content_digest", sa.String(length=80), nullable=False),
            sa.Column("decision", sa.String(length=16), nullable=False),
            sa.Column("reviewer_id", sa.String(length=120), nullable=False),
            sa.Column("reviewer_role", sa.String(length=48), nullable=False),
            sa.Column("note", sa.String(length=600), nullable=False),
            sa.Column("approved_seed_scope", sa.JSON(), nullable=False),
            sa.Column("reviewed_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["release_id"], ["knowledge_pack_release.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_knowledge_pack_review_release",
            "knowledge_pack_review",
            ["release_id", "reviewed_at"],
        )
    if "knowledge_pack_import" not in tables:
        op.create_table(
            "knowledge_pack_import",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("upload_sha256", sa.String(length=64), nullable=False),
            sa.Column("storage_path", sa.String(length=300), nullable=False),
            sa.Column("release_id", sa.String(length=64), nullable=True),
            sa.Column("reused_release", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    interview_columns = _columns("interview")
    with op.batch_alter_table("interview") as batch:
        if "pack_release_id" not in interview_columns:
            batch.add_column(
                sa.Column("pack_release_id", sa.String(length=64), nullable=True)
            )
        if "pack_content_digest" not in interview_columns:
            batch.add_column(
                sa.Column("pack_content_digest", sa.String(length=80), nullable=True)
            )
        if "competency_profile_id" not in interview_columns:
            batch.add_column(
                sa.Column("competency_profile_id", sa.String(length=64), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("interview") as batch:
        for name in (
            "competency_profile_id",
            "pack_content_digest",
            "pack_release_id",
        ):
            if name in _columns("interview"):
                batch.drop_column(name)
    if "knowledge_pack_import" in _tables():
        op.drop_table("knowledge_pack_import")
    if "knowledge_pack_review" in _tables():
        op.drop_index("ix_knowledge_pack_review_release", "knowledge_pack_review")
        op.drop_table("knowledge_pack_review")
    if "knowledge_pack_release" in _tables():
        op.drop_table("knowledge_pack_release")
