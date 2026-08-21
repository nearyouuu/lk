"""Normalize all profile and student-owned delete cascades.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


# These records have no independent meaning after their owner is deleted.
CASCADE_REFERENCES = (
    ("students", "user_id", "users"),
    ("admin_profiles", "user_id", "users"),
    ("directors", "user_id", "users"),
    ("user_roles", "user_id", "users"),
    ("achievements", "student_id", "students"),
    ("applications", "student_id", "students"),
    ("document_orders", "student_id", "students"),
    ("grades", "student_id", "students"),
    ("test_attempts", "student_id", "students"),
)


def _replace_fk(
    table_name: str,
    column_name: str,
    parent_table: str,
    ondelete: str | None,
) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if table_name not in table_names or parent_table not in table_names:
        return

    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in column_names:
        return

    # Legacy databases may contain rows created while the FK was absent.
    # They already have no owner and match the semantics of ON DELETE CASCADE.
    op.execute(
        sa.text(
            f"""
            DELETE FROM {table_name} AS child
            WHERE child.{column_name} IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM {parent_table} AS parent
                  WHERE parent.id = child.{column_name}
              )
            """
        )
    )

    foreign_keys = [
        fk
        for fk in sa.inspect(bind).get_foreign_keys(table_name)
        if fk.get("constrained_columns") == [column_name]
        and fk.get("referred_table") == parent_table
    ]
    for fk in foreign_keys:
        if fk.get("name"):
            op.drop_constraint(fk["name"], table_name, type_="foreignkey")

    op.create_foreign_key(
        f"{table_name}_{column_name}_fkey",
        table_name,
        parent_table,
        [column_name],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table_name, column_name, parent_table in CASCADE_REFERENCES:
        _replace_fk(table_name, column_name, parent_table, ondelete="CASCADE")


def downgrade() -> None:
    for table_name, column_name, parent_table in reversed(CASCADE_REFERENCES):
        _replace_fk(table_name, column_name, parent_table, ondelete=None)
