"""Normalize journal lesson types and remove slot uniqueness.

Revision ID: 93a4b5c6d7e8
Revises: 8293a4b5c6d7
Create Date: 2026-09-03
"""

from alembic import op


revision = "93a4b5c6d7e8"
down_revision = "8293a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE name = 'student')
          AND permission_id IN (
              SELECT id FROM permissions WHERE code = 'journal.read'
          )
        """
    )

    op.drop_constraint("ck_journal_lessons_type", "journal_lessons", type_="check")
    op.drop_constraint("ck_lessons_subject_type", "lessons", type_="check")

    op.execute(
        "UPDATE journal_lessons "
        "SET lesson_type = 'educational_practice' "
        "WHERE lesson_type = 'lab'"
    )
    op.execute(
        "UPDATE lessons "
        "SET subject_type = 'educational_practice' "
        "WHERE subject_type = 'lab'"
    )

    op.create_check_constraint(
        "ck_journal_lessons_type",
        "journal_lessons",
        "lesson_type IN ('lecture', 'practice', 'educational_practice')",
    )
    op.create_check_constraint(
        "ck_lessons_subject_type",
        "lessons",
        "subject_type IS NULL OR subject_type IN "
        "('lecture', 'practice', 'educational_practice')",
    )

    op.drop_constraint("uq_journal_lesson_slot", "journal_lessons", type_="unique")
    op.create_index(
        "ix_journal_lessons_topic_id",
        "journal_lessons",
        ["topic_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_journal_lessons_topic_id", table_name="journal_lessons")
    op.create_unique_constraint(
        "uq_journal_lesson_slot",
        "journal_lessons",
        ["group_id", "subject_id", "lesson_date", "starts_at"],
    )

    op.drop_constraint("ck_journal_lessons_type", "journal_lessons", type_="check")
    op.drop_constraint("ck_lessons_subject_type", "lessons", type_="check")

    op.execute(
        "UPDATE journal_lessons "
        "SET lesson_type = 'lab' "
        "WHERE lesson_type = 'educational_practice'"
    )
    op.execute(
        "UPDATE lessons "
        "SET subject_type = 'lab' "
        "WHERE subject_type = 'educational_practice'"
    )

    op.create_check_constraint(
        "ck_journal_lessons_type",
        "journal_lessons",
        "lesson_type IN ('lecture', 'practice', 'lab')",
    )
    op.create_check_constraint(
        "ck_lessons_subject_type",
        "lessons",
        "subject_type IS NULL OR subject_type IN ('lecture', 'practice', 'lab')",
    )

    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT role.id, permission.id
        FROM roles AS role
        CROSS JOIN permissions AS permission
        WHERE role.name = 'student'
          AND permission.code = 'journal.read'
          AND NOT EXISTS (
              SELECT 1
              FROM role_permissions AS existing
              WHERE existing.role_id = role.id
                AND existing.permission_id = permission.id
          )
        """
    )
