"""add bonus_credits to promo_codes

Revision ID: 20260320_add_bonus_credits_to_promo_codes
Revises: 20260222_create_app_setting
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260320_add_bonus_credits_to_promo_codes"
down_revision = "20260222_create_app_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "promo_codes",
        sa.Column("bonus_credits", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("promo_codes", "bonus_credits", server_default=None)


def downgrade() -> None:
    op.drop_column("promo_codes", "bonus_credits")
