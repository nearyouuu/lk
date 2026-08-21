"""split lesson subject types from subject grade types

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This intentionally stays nullable for existing installations: the control
    # form cannot be inferred from lecture/practice/lab. Administrators must
    # backfill it before a later migration makes the column NOT NULL.
    op.add_column("subjects", sa.Column("grade_type", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        "ck_subjects_grade_type",
        "subjects",
        "grade_type IN ('exam', 'зачет')",
    )
    # Legacy installations may have the FK under a different generated name,
    # or may not have it at all. Drop every FK attached to subjects.type_id
    # before removing the obsolete column.
    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN unnest(c.conkey) AS key(attnum) ON TRUE
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key.attnum
                WHERE c.contype = 'f'
                  AND n.nspname = current_schema()
                  AND t.relname = 'subjects'
                  AND a.attname = 'type_id'
            LOOP
                EXECUTE format('ALTER TABLE subjects DROP CONSTRAINT %I', constraint_name);
            END LOOP;
        END $$;
        """
    )
    op.drop_column("subjects", "type_id")

    op.alter_column(
        "lessons",
        "lesson_type",
        new_column_name="subject_type",
        existing_type=sa.String(length=50),
        existing_nullable=True,
    )
    op.execute(
        "UPDATE lessons SET subject_type = NULL "
        "WHERE subject_type IS NOT NULL AND subject_type NOT IN ('lecture', 'practice', 'lab')"
    )
    op.alter_column(
        "lessons",
        "subject_type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.create_check_constraint(
        "ck_lessons_subject_type",
        "lessons",
        "subject_type IS NULL OR subject_type IN ('lecture', 'practice', 'lab')",
    )

    # Convert only subjects that have been explicitly backfilled. No default to
    # exam is used because that would silently change the meaning of old data.
    op.execute(
        """
        UPDATE grades AS g
        SET grade_type = s.grade_type
        FROM subjects AS s
        WHERE g.subject_id = s.id
          AND g.grade_type IN ('итог', 'final')
          AND s.grade_type IN ('exam', 'зачет')
        """
    )
    op.create_index(
        "uq_grades_final_student_subject_semester",
        "grades",
        ["student_id", "subject_id", "semester_year", "semester_season"],
        unique=True,
        postgresql_where=sa.text("lesson_id IS NULL AND grade_type IN ('exam', 'зачет')"),
        sqlite_where=sa.text("lesson_id IS NULL AND grade_type IN ('exam', 'зачет')"),
    )


def downgrade() -> None:
    op.drop_index("uq_grades_final_student_subject_semester", table_name="grades")
    op.drop_constraint("ck_lessons_subject_type", "lessons", type_="check")
    op.alter_column(
        "lessons",
        "subject_type",
        new_column_name="lesson_type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.drop_constraint("ck_subjects_grade_type", "subjects", type_="check")
    op.drop_column("subjects", "grade_type")
    op.add_column("subjects", sa.Column("type_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "subjects_type_id_fkey",
        "subjects",
        "subject_types",
        ["type_id"],
        ["id"],
        ondelete="SET NULL",
    )
