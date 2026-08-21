"""add semester to grades

Revision ID: e4f5a6b7c8d9
Revises: a1b2c3d4e5f6
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "e4f5a6b7c8d9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("grades")}

    if not columns["teacher_id"]["nullable"]:
        op.alter_column("grades", "teacher_id", existing_type=sa.Integer(), nullable=True)
    if "semester_year" not in columns:
        op.add_column("grades", sa.Column("semester_year", sa.Integer(), nullable=True))
    if "semester_season" not in columns:
        op.add_column("grades", sa.Column("semester_season", sa.String(length=10), nullable=True))

    # Some installations received these columns through the emergency SQL
    # script before this Alembic revision existed. Complete only the missing
    # schema objects so Alembic can safely adopt that database.
    check_names = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints("grades")
        if constraint.get("name")
    }
    if "ck_grades_semester_season" not in check_names:
        op.create_check_constraint(
            "ck_grades_semester_season",
            "grades",
            "semester_season IS NULL OR semester_season IN ('весна', 'осень')",
        )

    index_names = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("grades")
        if index.get("name")
    }
    if "ix_grades_semester_year" not in index_names:
        op.create_index("ix_grades_semester_year", "grades", ["semester_year"], unique=False)
    if "ix_grades_semester_season" not in index_names:
        op.create_index("ix_grades_semester_season", "grades", ["semester_season"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_grades_semester_season", table_name="grades")
    op.drop_index("ix_grades_semester_year", table_name="grades")
    op.drop_constraint("ck_grades_semester_season", "grades", type_="check")
    op.drop_column("grades", "semester_season")
    op.drop_column("grades", "semester_year")
    op.alter_column("grades", "teacher_id", existing_type=sa.Integer(), nullable=False)
