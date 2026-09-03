"""Backfill subject teachers and normalize journal lesson types.

Revision ID: 60718293a4b5
Revises: 5f60718293a4
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "60718293a4b5"
down_revision = "5f60718293a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO teacher_subjects (teacher_id, subject_id)
        SELECT primary_teacher_id, id
        FROM subjects
        WHERE primary_teacher_id IS NOT NULL
        ON CONFLICT (teacher_id, subject_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE journal_lessons
        SET lesson_type = 'practice'
        WHERE lesson_type IS NULL
           OR lesson_type NOT IN ('lecture', 'practice', 'lab')
        """
    )
    op.alter_column(
        "journal_lessons",
        "lesson_type",
        existing_type=sa.String(length=20),
        nullable=False,
    )


def downgrade() -> None:
    # teacher_subjects may contain links created after the migration and must be preserved.
    op.alter_column(
        "journal_lessons",
        "lesson_type",
        existing_type=sa.String(length=20),
        nullable=True,
    )
