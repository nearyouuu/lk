"""merge legacy and current migration heads

Revision ID: a1b2c3d4e5f6
Revises: 6120411d26c1, 9d0b7a1f2c3d
Create Date: 2026-06-23 10:52:00

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = ("6120411d26c1", "9d0b7a1f2c3d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
