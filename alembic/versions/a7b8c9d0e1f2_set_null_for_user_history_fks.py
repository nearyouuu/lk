"""Keep historical records when a user is deleted.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


USER_REFERENCES = (
    ("audit_logs", "user_id", True),
    ("grades", "modified_by_admin_id", True),
    ("news", "author_id", False),
    ("tests", "created_by_id", False),
    ("test_attempts", "reviewed_by_user_id", True),
    ("teachers", "user_id", True),
    ("lessons", "created_by", True),
)


def _replace_user_fk(table_name: str, column_name: str, nullable: bool, ondelete: str | None) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    column = next(
        column
        for column in inspector.get_columns(table_name)
        if column["name"] == column_name
    )
    if bool(column["nullable"]) != nullable:
        op.alter_column(
            table_name,
            column_name,
            existing_type=column["type"],
            nullable=nullable,
        )

    foreign_keys = [
        fk
        for fk in sa.inspect(bind).get_foreign_keys(table_name)
        if fk.get("constrained_columns") == [column_name]
        and fk.get("referred_table") == "users"
    ]
    for fk in foreign_keys:
        if fk.get("name"):
            op.drop_constraint(fk["name"], table_name, type_="foreignkey")

    op.create_foreign_key(
        f"{table_name}_{column_name}_fkey",
        table_name,
        "users",
        [column_name],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table_name, column_name, _was_nullable in USER_REFERENCES:
        _replace_user_fk(table_name, column_name, nullable=True, ondelete="SET NULL")


def downgrade() -> None:
    for table_name, column_name, was_nullable in USER_REFERENCES:
        _replace_user_fk(table_name, column_name, nullable=was_nullable, ondelete=None)
