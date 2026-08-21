"""legacy init schema placeholder

Revision ID: 04329eda6002
Revises: 861588fcdc83
Create Date: 2025-09-23 11:27:28.940688

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "04329eda6002"
down_revision: Union[str, None] = "861588fcdc83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Historical placeholder for databases restored from older backups.
    # The schema already exists; we only preserve the Alembic revision graph.
    pass


def downgrade() -> None:
    pass
