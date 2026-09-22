"""Persist per-snapshot Knowledge activation and backfill proven receipts.

Revision ID: e62a9f8c10bd
Revises: b4d7c2e91f30
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e62a9f8c10bd"
down_revision: str | Sequence[str] | None = "b4d7c2e91f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    table_names = set(sa.inspect(connection).get_table_names())
    if "profile_snapshot_activation" not in table_names:
        activation = op.create_table(
            "profile_snapshot_activation",
            sa.Column("snapshot_id", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("operation_id", sa.String(length=128), nullable=True),
            sa.Column("receipt", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["snapshot_id"], ["profile_snapshot.id"]),
            sa.ForeignKeyConstraint(["operation_id"], ["operation.id"]),
            sa.PrimaryKeyConstraint("snapshot_id"),
            sa.UniqueConstraint("operation_id"),
        )
        existing_snapshot_ids: set[str] = set()
    else:
        activation = sa.table(
            "profile_snapshot_activation",
            sa.column("snapshot_id"),
            sa.column("status"),
            sa.column("operation_id"),
            sa.column("receipt", sa.JSON()),
            sa.column("created_at"),
            sa.column("updated_at"),
        )
        existing_snapshot_ids = set(
            connection.execute(sa.select(activation.c.snapshot_id)).scalars()
        )

    snapshots = sa.table(
        "profile_snapshot",
        sa.column("id"),
        sa.column("profile_id"),
        sa.column("confirmed_claim_ids", sa.JSON()),
        sa.column("created_at"),
    )
    operations = sa.table(
        "operation",
        sa.column("id"),
        sa.column("kind"),
        sa.column("resource_id"),
        sa.column("status"),
        sa.column("result", sa.JSON()),
        sa.column("updated_at"),
    )
    # A Document ready flag is not a generation receipt. Only a succeeded
    # confirmation whose result names this exact generation and full source set
    # proves historical activation; every other snapshot remains explicitly pending.
    proven = {}
    for operation in connection.execute(
        sa.select(operations)
        .where(
            operations.c.kind == "profile.confirm",
            operations.c.status == "succeeded",
        )
        .order_by(operations.c.updated_at, operations.c.id)
    ).mappings():
        result = operation["result"]
        if isinstance(result, dict) and isinstance(
            result.get("profile_snapshot_id"), str
        ):
            proven[result["profile_snapshot_id"]] = operation
    for snapshot in connection.execute(sa.select(snapshots)).mappings():
        if snapshot["id"] in existing_snapshot_ids:
            continue
        operation = proven.get(snapshot["id"])
        result = operation["result"] if operation is not None else {}
        expected = {
            f"{snapshot['id']}:{claim_id}"
            for claim_id in snapshot["confirmed_claim_ids"] or []
        }
        sources = result.get("source_ids")
        ready = (
            operation is not None
            and operation["resource_id"] == snapshot["profile_id"]
            and result.get("knowledge_generation") == snapshot["id"]
            and isinstance(sources, list)
            and all(isinstance(source, str) for source in sources)
            and bool(expected)
            and len(sources) == len(expected)
            and set(sources) == expected
        )
        connection.execute(
            activation.insert().values(
                snapshot_id=snapshot["id"],
                status="ready" if ready else "pending",
                operation_id=operation["id"] if ready else None,
                receipt={"generation": snapshot["id"], "source_ids": sources}
                if ready
                else None,
                created_at=snapshot["created_at"],
                updated_at=operation["updated_at"] if ready else snapshot["created_at"],
            )
        )


def downgrade() -> None:
    op.drop_table("profile_snapshot_activation")
