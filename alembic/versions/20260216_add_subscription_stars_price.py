"""add stars_price to subscription

Revision ID: 20260216_add_subscription_stars_price
Revises: 20260208_create_admin_action_logs
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260216_add_subscription_stars_price"
down_revision = "20260208_create_admin_action_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription",
        sa.Column("stars_price", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("subscription", "stars_price", server_default=None)


def downgrade() -> None:
    op.drop_column("subscription", "stars_price")
