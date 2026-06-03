"""set agent price to 10 credits

Revision ID: 20260603_set_agent_price_to_10
Revises: 20260602_add_agent_billing_fields
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260603_set_agent_price_to_10"
down_revision = "20260602_add_agent_billing_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO app_setting (key, int_value)
            VALUES (:key, :value)
            ON CONFLICT(key) DO UPDATE SET int_value = excluded.int_value
            """
        ).bindparams(key="model_price_wearai_agent_request", value=10)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_setting
            SET int_value = :value
            WHERE key = :key
            """
        ).bindparams(key="model_price_wearai_agent_request", value=5)
    )
