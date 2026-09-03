"""Remove legacy journal lesson uniqueness constraints.

Revision ID: a4b5c6d7e8f9
Revises: 93a4b5c6d7e8
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op


revision = "a4b5c6d7e8f9"
down_revision = "93a4b5c6d7e8"
branch_labels = None
depends_on = None


LEGACY_UNIQUES = {
    "uq_journal_lesson_slot",
    "uq_journal_lesson_day_type",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("journal_lessons")
        if constraint.get("name")
    }
    for constraint_name in sorted(LEGACY_UNIQUES & unique_constraints):
        op.drop_constraint(constraint_name, "journal_lessons", type_="unique")

    inspector = sa.inspect(bind)
    indexes = {
        index["name"]: index
        for index in inspector.get_indexes("journal_lessons")
        if index.get("name")
    }
    for index_name in sorted(LEGACY_UNIQUES & indexes.keys()):
        op.drop_index(index_name, table_name="journal_lessons")

    if "ix_journal_lessons_topic_id" not in indexes:
        op.create_index(
            "ix_journal_lessons_topic_id",
            "journal_lessons",
            ["topic_id"],
            unique=False,
        )

    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE name = 'student')
          AND permission_id IN (
              SELECT id FROM permissions WHERE code = 'journal.read'
          )
        """
    )


def downgrade() -> None:
    # Legacy uniqueness is intentionally not restored: repeated lessons are valid data.
    pass
