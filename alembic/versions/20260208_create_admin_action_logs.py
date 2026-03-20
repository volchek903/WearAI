"""create admin action logs

Revision ID: 20260208_create_admin_action_logs
Revises: 20260208_create_promo_codes
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260208_create_admin_action_logs"
down_revision = "20260208_create_promo_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tg_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("data", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_admin_action_logs_user_id", "admin_action_logs", ["user_id"]
    )
    op.create_index(
        "ix_admin_action_logs_tg_id", "admin_action_logs", ["tg_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_action_logs_tg_id", table_name="admin_action_logs")
    op.drop_index("ix_admin_action_logs_user_id", table_name="admin_action_logs")
    op.drop_table("admin_action_logs")
