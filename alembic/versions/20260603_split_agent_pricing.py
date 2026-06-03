"""split agent pricing into base request and addons

Revision ID: 20260603_split_agent_pricing
Revises: 20260603_set_agent_price_to_10
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260603_split_agent_pricing"
down_revision = "20260603_set_agent_price_to_10"
branch_labels = None
depends_on = None


def _upsert_setting(key: str, value: int) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO app_setting (key, int_value)
            VALUES (:key, :value)
            ON CONFLICT(key) DO UPDATE SET int_value = excluded.int_value
            """
        ).bindparams(key=key, value=value)
    )


def upgrade() -> None:
    _upsert_setting("model_price_wearai_agent_request", 5)
    _upsert_setting("model_price_wearai_agent_memory_addon", 2)
    _upsert_setting("model_price_wearai_agent_documents_addon", 2)
    _upsert_setting("model_price_wearai_agent_web_search_addon", 1)
    _upsert_setting("model_price_wearai_agent_deep_analysis_addon", 1)
    _upsert_setting("model_price_wearai_agent_quick_mode_addon", 1)


def downgrade() -> None:
    _upsert_setting("model_price_wearai_agent_request", 10)
    op.execute(
        sa.text(
            """
            DELETE FROM app_setting
            WHERE key IN (
                'model_price_wearai_agent_memory_addon',
                'model_price_wearai_agent_documents_addon',
                'model_price_wearai_agent_web_search_addon',
                'model_price_wearai_agent_deep_analysis_addon',
                'model_price_wearai_agent_quick_mode_addon'
            )
            """
        )
    )
