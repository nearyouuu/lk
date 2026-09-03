"""Add a stable unique subject identifier.

Revision ID: 8293a4b5c6d7
Revises: 718293a4b5c6
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "8293a4b5c6d7"
down_revision = "718293a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("identifier", sa.String(length=64), nullable=True))
    op.execute("UPDATE subjects SET identifier = 'subject-' || id::text WHERE identifier IS NULL")
    op.alter_column("subjects", "identifier", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_subjects_identifier", "subjects", ["identifier"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_subjects_identifier", table_name="subjects")
    op.drop_column("subjects", "identifier")
