"""create generation_log

Revision ID: 20260222_create_generation_log
Revises: 20260216_add_subscription_stars_price
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260222_create_generation_log"
down_revision = "20260216_add_subscription_stars_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("subscription.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_subscription_id",
            sa.Integer(),
            sa.ForeignKey("user_subscription.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_generation_log_user_id", "generation_log", ["user_id"])
    op.create_index(
        "ix_generation_log_subscription_id",
        "generation_log",
        ["subscription_id"],
    )
    op.create_index(
        "ix_generation_log_user_subscription_id",
        "generation_log",
        ["user_subscription_id"],
    )
    op.create_index("ix_generation_log_kind", "generation_log", ["kind"])
    op.create_index("ix_generation_log_created_at", "generation_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_generation_log_created_at", table_name="generation_log")
    op.drop_index("ix_generation_log_kind", table_name="generation_log")
    op.drop_index("ix_generation_log_user_subscription_id", table_name="generation_log")
    op.drop_index("ix_generation_log_subscription_id", table_name="generation_log")
    op.drop_index("ix_generation_log_user_id", table_name="generation_log")
    op.drop_table("generation_log")
