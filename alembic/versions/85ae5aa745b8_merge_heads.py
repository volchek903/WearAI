"""merge heads

Revision ID: 85ae5aa745b8
Revises: 20260127_create_referrals, 20260208_add_generated_videos
Create Date: 2026-02-08 17:34:48.824827+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85ae5aa745b8'
down_revision: Union[str, Sequence[str], None] = ('20260127_create_referrals', '20260208_add_generated_videos')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
