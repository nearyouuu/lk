"""legacy-safe init schema placeholder

Revision ID: 6120411d26c1
Revises: dd90bf10df7d
Create Date: 2025-10-27 08:06:31.445223

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "6120411d26c1"
down_revision: Union[str, None] = "dd90bf10df7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The database may already contain the full schema from an older backup.
    # Keep this revision as a no-op so Alembic can converge to a single head
    # without trying to recreate existing tables.
    pass


def downgrade() -> None:
    pass
