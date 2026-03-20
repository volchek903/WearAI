"""add generated_videos to users

Revision ID: 20260208_add_generated_videos
Revises: 20260127_add_referrals
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260208_add_generated_videos"
down_revision = "20260127_add_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "generated_videos", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.alter_column("users", "generated_videos", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "generated_videos")
