"""Bind owner rule approval to exact profile bytes; preserve legacy NULLs.

Revision ID: d63b8a24f710
Revises: c91f8b34d602
"""

import sqlalchemy as sa
from alembic import op

revision = "d63b8a24f710"
down_revision = "c91f8b34d602"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        c["name"]
        for c in sa.inspect(op.get_bind()).get_columns("knowledge_pack_review")
    }


def upgrade() -> None:
    existing = _columns()
    for name, kind in (
        ("competency_profile_id", sa.String(64)),
        ("profile_version", sa.String(32)),
        ("profile_digest", sa.String(80)),
        ("level1_reviewed", sa.Boolean()),
        ("level2_reviewed", sa.Boolean()),
        ("rules_reviewed", sa.Boolean()),
    ):
        if name not in existing:
            op.add_column("knowledge_pack_review", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    existing = _columns()
    with op.batch_alter_table("knowledge_pack_review") as batch:
        for name in (
            "rules_reviewed",
            "level2_reviewed",
            "level1_reviewed",
            "profile_digest",
            "profile_version",
            "competency_profile_id",
        ):
            if name in existing:
                batch.drop_column(name)
