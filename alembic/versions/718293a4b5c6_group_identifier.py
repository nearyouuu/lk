"""Add a stable unique group identifier and allow duplicate group labels.

Revision ID: 718293a4b5c6
Revises: 60718293a4b5
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "718293a4b5c6"
down_revision = "60718293a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("identifier", sa.String(length=64), nullable=True))
    op.execute("UPDATE groups SET identifier = 'group-' || id::text WHERE identifier IS NULL")
    op.alter_column("groups", "identifier", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_groups_identifier", "groups", ["identifier"], unique=True)
    op.execute("ALTER TABLE groups DROP CONSTRAINT IF EXISTS groups_code_key")
    op.execute("DROP INDEX IF EXISTS ix_groups_code")
    op.create_index("ix_groups_code", "groups", ["code"], unique=False)


def downgrade() -> None:
    duplicate = op.get_bind().execute(sa.text(
        "SELECT code FROM groups GROUP BY code HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("Cannot restore unique group codes while duplicate codes exist")
    op.drop_index("ix_groups_code", table_name="groups")
    op.create_unique_constraint("groups_code_key", "groups", ["code"])
    op.drop_index("ix_groups_identifier", table_name="groups")
    op.drop_column("groups", "identifier")
