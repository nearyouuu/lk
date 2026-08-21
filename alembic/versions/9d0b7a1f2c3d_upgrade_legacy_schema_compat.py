"""upgrade legacy schema for current backend compatibility

Revision ID: 9d0b7a1f2c3d
Revises: 6120411d26c1
Create Date: 2026-06-23 10:45:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9d0b7a1f2c3d"
down_revision: Union[str, Sequence[str], None] = ("04329eda6002", "2abb77daac61")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This migration is intentionally defensive: the project may be running
    # against an older PostgreSQL schema restored from backups, so we only add
    # missing objects and keep new columns nullable where existing data cannot
    # be reconstructed safely.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_types (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE
        );
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'subjects' AND column_name = 'type_id'
            ) THEN
                ALTER TABLE subjects ADD COLUMN type_id INTEGER NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'subjects_type_id_fkey'
            ) THEN
                ALTER TABLE subjects
                ADD CONSTRAINT subjects_type_id_fkey
                FOREIGN KEY (type_id) REFERENCES subject_types(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_subjects (
            teacher_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            PRIMARY KEY (teacher_id, subject_id),
            CONSTRAINT teacher_subjects_teacher_id_fkey
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
            CONSTRAINT teacher_subjects_subject_id_fkey
                FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_teachers (
            lesson_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            PRIMARY KEY (lesson_id, teacher_id),
            CONSTRAINT lesson_teachers_lesson_id_fkey
                FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE,
            CONSTRAINT lesson_teachers_teacher_id_fkey
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_times (
            id SERIAL PRIMARY KEY,
            lesson_number INTEGER NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL
        );
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'lesson_times'
                  AND indexname = 'ix_lesson_times_lesson_number'
            ) THEN
                CREATE UNIQUE INDEX ix_lesson_times_lesson_number
                    ON lesson_times (lesson_number);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'lessons' AND column_name = 'lesson_number'
            ) THEN
                ALTER TABLE lessons ADD COLUMN lesson_number INTEGER NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'grades' AND column_name = 'modified_by_admin_id'
            ) THEN
                ALTER TABLE grades ADD COLUMN modified_by_admin_id INTEGER NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'grades_modified_by_admin_id_fkey'
            ) THEN
                ALTER TABLE grades
                ADD CONSTRAINT grades_modified_by_admin_id_fkey
                FOREIGN KEY (modified_by_admin_id) REFERENCES users(id);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'grades'
                  AND indexname = 'ix_grades_modified_by_admin_id'
            ) THEN
                CREATE INDEX ix_grades_modified_by_admin_id
                    ON grades (modified_by_admin_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Legacy compatibility migration is intentionally non-destructive.
    pass
