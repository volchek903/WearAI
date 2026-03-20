"""create app_setting

Revision ID: 20260222_create_app_setting
Revises: 20260222_create_generation_log
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260222_create_app_setting"
down_revision = "20260222_create_generation_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("int_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_app_setting_key", "app_setting", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_setting_key", table_name="app_setting")
    op.drop_table("app_setting")
