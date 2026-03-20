"""baseline

Revision ID: 8f660d1136d5
Revises: a4e74753f740
Create Date: 2026-01-09 09:56:36.075245+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f660d1136d5'
down_revision: Union[str, Sequence[str], None] = 'a4e74753f740'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
