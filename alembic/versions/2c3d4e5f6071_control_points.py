"""Add journal control points and rating statements.

Revision ID: 2c3d4e5f6071
Revises: 1b2c3d4e5f60
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "2c3d4e5f6071"
down_revision = "1b2c3d4e5f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_control_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("planned_lesson_number", sa.Integer(), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("journal_lesson_id", sa.Integer(), nullable=True),
        sa.Column("total_practical_hours", sa.Integer(), nullable=False),
        sa.Column("hours_per_lesson", sa.Integer(), nullable=False),
        sa.Column("current_max", sa.Numeric(5, 2), nullable=False, server_default="20"),
        sa.Column("attendance_max", sa.Numeric(5, 2), nullable=False),
        sa.Column("project_semester_max", sa.Numeric(5, 2), nullable=False, server_default="20"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("number BETWEEN 1 AND 3", name="ck_journal_control_point_number"),
        sa.CheckConstraint("status IN ('draft', 'published', 'locked')", name="ck_journal_control_point_status"),
        sa.CheckConstraint("current_max = 20", name="ck_journal_control_point_current_max"),
        sa.CheckConstraint("attendance_max IN (3, 4)", name="ck_journal_control_point_attendance_max"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["period_id"], ["journal_periods.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["journal_lesson_id"], ["journal_lessons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("group_id", "subject_id", "period_id", "number", name="uq_journal_control_point_number"),
    )
    op.create_index(
        "ix_journal_control_points_group_subject_period",
        "journal_control_points",
        ["group_id", "subject_id", "period_id"],
    )

    op.create_table(
        "journal_control_point_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("control_point_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("current_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("attendance_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("calculated_attendance_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("attendance_is_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eligible_lessons", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attended_lessons", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("project_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("current_score >= 0 AND current_score <= 20", name="ck_journal_cp_current_score"),
        sa.CheckConstraint("project_score >= 0 AND project_score <= 20", name="ck_journal_cp_project_score"),
        sa.CheckConstraint("attendance_score >= 0 AND attendance_score <= 4", name="ck_journal_cp_attendance_score"),
        sa.CheckConstraint(
            "calculated_attendance_score >= 0 AND calculated_attendance_score <= 4",
            name="ck_journal_cp_calculated_attendance_score",
        ),
        sa.ForeignKeyConstraint(["control_point_id"], ["journal_control_points.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("control_point_id", "student_id", name="uq_journal_control_point_student"),
    )
    op.create_index(
        "ix_journal_control_point_scores_control_point_id",
        "journal_control_point_scores",
        ["control_point_id"],
    )
    op.create_index(
        "ix_journal_control_point_scores_student_id",
        "journal_control_point_scores",
        ["student_id"],
    )


def downgrade() -> None:
    op.drop_table("journal_control_point_scores")
    op.drop_table("journal_control_points")
