"""Allow long subject lists in teacher profiles.

Revision ID: 0a1b2c3d4e5f
Revises: f7a8b9c0d1e2
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0a1b2c3d4e5f"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "teachers",
        "subject",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "teachers",
        "subject",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
