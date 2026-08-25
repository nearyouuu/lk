"""Add independent study journal module.

Revision ID: 1b2c3d4e5f60
Revises: 0a1b2c3d4e5f
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "1b2c3d4e5f60"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subject_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("sort_order >= 0", name="ck_subject_topics_sort_order"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_subject_topics_subject_id", "subject_topics", ["subject_id"])
    op.create_index("ix_subject_topics_subject_sort", "subject_topics", ["subject_id", "sort_order"])

    op.create_table(
        "journal_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("semester", sa.String(length=10), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("semester IN ('autumn', 'spring')", name="ck_journal_period_semester"),
        sa.ForeignKeyConstraint(["locked_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("academic_year", "semester", name="uq_journal_period_year_semester"),
    )
    op.create_index("ix_journal_periods_academic_year", "journal_periods", ["academic_year"])

    op.create_table(
        "journal_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("semester", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("semester IN ('autumn', 'spring')", name="ck_journal_assignment_semester"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("teacher_id", "group_id", "subject_id", "academic_year", "semester", name="uq_journal_assignment"),
    )
    for column in ("teacher_id", "group_id", "subject_id", "academic_year"):
        op.create_index(f"ix_journal_assignments_{column}", "journal_assignments", [column])

    op.create_table(
        "journal_lessons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("starts_at", sa.Time(), nullable=True),
        sa.Column("ends_at", sa.Time(), nullable=True),
        sa.Column("lesson_type", sa.String(length=20), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("topic_text", sa.String(length=500), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("schedule_lesson_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("lesson_type IN ('lecture', 'practice', 'lab')", name="ck_journal_lessons_type"),
        sa.CheckConstraint("status IN ('draft', 'published', 'cancelled')", name="ck_journal_lessons_status"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["period_id"], ["journal_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["topic_id"], ["subject_topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["schedule_lesson_id"], ["lessons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("group_id", "subject_id", "lesson_date", "starts_at", name="uq_journal_lesson_slot"),
        sa.UniqueConstraint("schedule_lesson_id", name="uq_journal_lessons_schedule_lesson_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_journal_lessons_idempotency_key"),
    )
    op.create_index("ix_journal_lessons_period_id", "journal_lessons", ["period_id"])
    op.create_index("ix_journal_lessons_group_subject_date", "journal_lessons", ["group_id", "subject_id", "lesson_date"])

    op.create_table(
        "journal_lesson_students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("record_book", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["lesson_id"], ["journal_lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("lesson_id", "student_id", name="uq_journal_lesson_student"),
    )
    op.create_index("ix_journal_lesson_students_lesson_id", "journal_lesson_students", ["lesson_id"])
    op.create_index("ix_journal_lesson_students_student_id", "journal_lesson_students", ["student_id"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("attendance", sa.String(length=20), nullable=False, server_default="present"),
        sa.Column("grade", sa.String(length=16), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("attendance IN ('present', 'absent', 'late', 'excused')", name="ck_journal_entries_attendance"),
        sa.ForeignKeyConstraint(["lesson_id"], ["journal_lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("lesson_id", "student_id", name="uq_journal_entry_lesson_student"),
    )
    op.create_index("ix_journal_entries_lesson_id", "journal_entries", ["lesson_id"])
    op.create_index("ix_journal_entries_student_id", "journal_entries", ["student_id"])

    op.create_table(
        "journal_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("entity", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=True),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lesson_id"], ["journal_lessons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
    )
    for column in ("actor_id", "lesson_id", "student_id", "request_id", "created_at"):
        op.create_index(f"ix_journal_audit_events_{column}", "journal_audit_events", [column])
    op.create_index("ix_journal_audit_entity", "journal_audit_events", ["entity", "entity_id"])

    codes = (
        "journal.read",
        "journal.lesson.write",
        "journal.entry.write",
        "journal.topic.manage",
        "journal.period.lock",
        "journal.audit.read",
    )
    for code in codes:
        op.execute(
            sa.text(
                "INSERT INTO permissions (code, description) "
                "SELECT :code, :code WHERE NOT EXISTS "
                "(SELECT 1 FROM permissions WHERE code = :code)"
            ).bindparams(code=code)
        )
    quoted_codes = ", ".join(f"'{code}'" for code in codes)
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            f"WHERE r.name IN ('administrator', 'director') AND p.code IN ({quoted_codes}) "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            "WHERE r.name = 'teacher' "
            "AND p.code IN ('journal.read', 'journal.lesson.write', 'journal.entry.write') "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )


def downgrade() -> None:
    op.drop_table("journal_audit_events")
    op.drop_table("journal_entries")
    op.drop_table("journal_lesson_students")
    op.drop_table("journal_lessons")
    op.drop_table("journal_assignments")
    op.drop_table("journal_periods")
    op.drop_table("subject_topics")
