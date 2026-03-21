"""add perf indexes for start and payments lookups

Revision ID: 20260321_add_perf_indexes_for_start
Revises: 20260320_add_bonus_credits_to_promo_codes
Create Date: 2026-03-21
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260321_add_perf_indexes_for_start"
down_revision = "20260320_add_bonus_credits_to_promo_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_users_free_generations_day",
        "users",
        ["free_generations_day"],
        unique=False,
    )
    op.create_index(
        "ix_payments_user_tg_status_id",
        "payments",
        ["user_tg_id", "status", "id"],
        unique=False,
    )
    op.create_index(
        "ix_payments_status_id",
        "payments",
        ["status", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payments_status_id", table_name="payments")
    op.drop_index("ix_payments_user_tg_status_id", table_name="payments")
    op.drop_index("ix_users_free_generations_day", table_name="users")
