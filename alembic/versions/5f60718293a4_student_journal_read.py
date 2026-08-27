"""Grant students read-only access to their study journal.

Revision ID: 5f60718293a4
Revises: 4e5f60718293
Create Date: 2026-08-26
"""

from alembic import op


revision = "5f60718293a4"
down_revision = "4e5f60718293"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT role.id, permission.id
        FROM roles AS role
        CROSS JOIN permissions AS permission
        WHERE role.name = 'student'
          AND permission.code = 'journal.read'
          AND NOT EXISTS (
              SELECT 1
              FROM role_permissions AS existing
              WHERE existing.role_id = role.id
                AND existing.permission_id = permission.id
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE name = 'student')
          AND permission_id IN (
              SELECT id FROM permissions WHERE code = 'journal.read'
          )
        """
    )
