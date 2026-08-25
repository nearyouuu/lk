"""Store journal hours and calculate control points by accumulated hours.

Revision ID: 4e5f60718293
Revises: 3d4e5f607182
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "4e5f60718293"
down_revision = "3d4e5f607182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journal_lessons",
        sa.Column("hours", sa.Integer(), nullable=False, server_default="2"),
    )
    op.create_check_constraint(
        "ck_journal_lessons_hours",
        "journal_lessons",
        "hours BETWEEN 1 AND 24",
    )
    op.execute(
        """
        UPDATE journal_lessons
        SET hours = LEAST(
            24,
            GREATEST(
                1,
                CEIL(EXTRACT(EPOCH FROM (ends_at - starts_at)) / 2700.0)::INTEGER
            )
        )
        WHERE starts_at IS NOT NULL AND ends_at IS NOT NULL
        """
    )

    op.add_column(
        "journal_control_points",
        sa.Column("planned_hours", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE journal_control_points
        SET planned_hours = CASE number
            WHEN 1 THEN CEIL(total_practical_hours / 3.0)::INTEGER
            WHEN 2 THEN CEIL(total_practical_hours * 2 / 3.0)::INTEGER
            ELSE total_practical_hours
        END
        """
    )


def downgrade() -> None:
    op.drop_column("journal_control_points", "planned_hours")
    op.drop_constraint("ck_journal_lessons_hours", "journal_lessons", type_="check")
    op.drop_column("journal_lessons", "hours")
