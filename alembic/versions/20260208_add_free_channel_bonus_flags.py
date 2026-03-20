"""add free channel bonus flags to users

Revision ID: 20260208_add_free_channel_bonus_flags
Revises: 85ae5aa745b8
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260208_add_free_channel_bonus_flags"
down_revision = "85ae5aa745b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "free_channel_bonus_used",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "free_channel_bonus_pending",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "free_channel_reminder_sent",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("users", "free_channel_bonus_used", server_default=None)
    op.alter_column("users", "free_channel_bonus_pending", server_default=None)
    op.alter_column("users", "free_channel_reminder_sent", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "free_channel_reminder_sent")
    op.drop_column("users", "free_channel_bonus_pending")
    op.drop_column("users", "free_channel_bonus_used")
