"""add user photo settings (duplicate/no-op)

Revision ID: 6f2eebab3220
Revises: 8f660d1136d5
Create Date: 2026-01-09 09:56:52.907846+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "6f2eebab3220"
down_revision: Union[str, Sequence[str], None] = "8f660d1136d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This revision was generated duplicating users/user_photo_settings creation.
    # Keep it as no-op to preserve revision graph.
    pass


def downgrade() -> None:
    pass
