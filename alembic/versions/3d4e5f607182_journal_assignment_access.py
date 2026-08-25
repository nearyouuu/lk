"""Use journal assignments as the only teacher access scope.

Revision ID: 3d4e5f607182
Revises: 2c3d4e5f6071
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "3d4e5f607182"
down_revision = "2c3d4e5f6071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve all access that was effective before this migration, but convert
    # it to explicit assignments once. Future schedule changes do not affect
    # journal authorization.
    op.execute(
        """
        INSERT INTO journal_assignments
            (teacher_id, group_id, subject_id, academic_year, semester, is_active, created_by)
        SELECT DISTINCT
            cp.teacher_id,
            cp.group_id,
            cp.subject_id,
            period.academic_year,
            period.semester,
            TRUE,
            cp.created_by
        FROM journal_control_points AS cp
        JOIN journal_periods AS period ON period.id = cp.period_id
        ON CONFLICT (teacher_id, group_id, subject_id, academic_year, semester) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO journal_assignments
            (teacher_id, group_id, subject_id, academic_year, semester, is_active, created_by)
        SELECT DISTINCT
            lesson.teacher_id,
            lesson.group_id,
            lesson.subject_id,
            period.academic_year,
            period.semester,
            TRUE,
            lesson.created_by
        FROM journal_lessons AS lesson
        JOIN journal_periods AS period ON period.id = lesson.period_id
        ON CONFLICT (teacher_id, group_id, subject_id, academic_year, semester) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO journal_assignments
            (teacher_id, group_id, subject_id, academic_year, semester, is_active, created_by)
        SELECT DISTINCT
            lesson.teacher_id,
            lesson.group_id,
            lesson.subject_id,
            CASE
                WHEN EXTRACT(MONTH FROM lesson.starts_at) >= 8
                    THEN EXTRACT(YEAR FROM lesson.starts_at)::INTEGER
                ELSE EXTRACT(YEAR FROM lesson.starts_at)::INTEGER - 1
            END,
            CASE
                WHEN EXTRACT(MONTH FROM lesson.starts_at) >= 8
                    OR EXTRACT(MONTH FROM lesson.starts_at) = 1
                    THEN 'autumn'
                ELSE 'spring'
            END,
            TRUE,
            lesson.created_by
        FROM lessons AS lesson
        WHERE lesson.teacher_id IS NOT NULL
          AND lesson.subject_id IS NOT NULL
        ON CONFLICT (teacher_id, group_id, subject_id, academic_year, semester) DO NOTHING
        """
    )

    # A control point belongs to the group/subject/period journal. Teacher access
    # is resolved through journal_assignments and is no longer stored per point.
    op.drop_column("journal_control_points", "teacher_id")


def downgrade() -> None:
    # The former owner cannot be reconstructed reliably when several teachers
    # share one journal, therefore the compatibility column is restored nullable.
    op.add_column(
        "journal_control_points",
        sa.Column("teacher_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_control_points_teacher_id_teachers",
        "journal_control_points",
        "teachers",
        ["teacher_id"],
        ["id"],
        ondelete="RESTRICT",
    )
