"""M4-01 enforce one assessment per root and one report per interview.

Revision ID: 7f1b9c4d2a60
Revises: 2c8f1d7a90b4
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f1b9c4d2a60"
down_revision: str | Sequence[str] | None = "2c8f1d7a90b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Protect deterministic report generation from duplicate business writes."""
    inspector = sa.inspect(op.get_bind())
    assessment_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("assessment")
    }
    if ("interview_id", "root_question_id") not in assessment_uniques:
        with op.batch_alter_table("assessment") as batch_op:
            batch_op.create_unique_constraint(
                "uq_assessment_interview_root",
                ["interview_id", "root_question_id"],
            )

    inspector = sa.inspect(op.get_bind())
    report_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("report")
    }
    if ("interview_id",) not in report_uniques:
        with op.batch_alter_table("report") as batch_op:
            batch_op.create_unique_constraint("uq_report_interview", ["interview_id"])


def downgrade() -> None:
    """Remove only the M4 report uniqueness constraints."""
    with op.batch_alter_table("report") as batch_op:
        batch_op.drop_constraint("uq_report_interview", type_="unique")
    with op.batch_alter_table("assessment") as batch_op:
        batch_op.drop_constraint("uq_assessment_interview_root", type_="unique")
