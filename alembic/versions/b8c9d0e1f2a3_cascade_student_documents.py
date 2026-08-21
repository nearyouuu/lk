"""Cascade student-owned applications and document orders.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


STUDENT_REFERENCES = (
    ("applications", "student_id"),
    ("document_orders", "student_id"),
)


def _replace_student_fk(table_name: str, column_name: str, ondelete: str | None) -> None:
    bind = op.get_bind()

    # Some legacy installations ran without these foreign keys and therefore
    # contain rows whose student was deleted long ago. Such rows cannot be
    # associated with any user and would have been removed by the CASCADE
    # constraint this migration installs, so clean them before adding it.
    op.execute(
        sa.text(
            f"""
            DELETE FROM {table_name} AS child
            WHERE NOT EXISTS (
                SELECT 1
                FROM students AS student
                WHERE student.id = child.{column_name}
            )
            """
        )
    )

    foreign_keys = [
        fk
        for fk in sa.inspect(bind).get_foreign_keys(table_name)
        if fk.get("constrained_columns") == [column_name]
        and fk.get("referred_table") == "students"
    ]
    for fk in foreign_keys:
        if fk.get("name"):
            op.drop_constraint(fk["name"], table_name, type_="foreignkey")

    op.create_foreign_key(
        f"{table_name}_{column_name}_fkey",
        table_name,
        "students",
        [column_name],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table_name, column_name in STUDENT_REFERENCES:
        _replace_student_fk(table_name, column_name, ondelete="CASCADE")


def downgrade() -> None:
    for table_name, column_name in STUDENT_REFERENCES:
        _replace_student_fk(table_name, column_name, ondelete=None)
