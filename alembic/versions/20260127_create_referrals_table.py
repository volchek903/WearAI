"""create referrals table

Revision ID: 20260127_create_referrals
Revises: 20260127_add_referrals
Create Date: 2026-01-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260127_create_referrals"
down_revision = "20260127_add_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("referrer_user_id", sa.Integer(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_referrals_referrer_user_id",
        "referrals",
        ["referrer_user_id"],
    )
    op.create_index(
        "ix_referrals_referred_user_id",
        "referrals",
        ["referred_user_id"],
        unique=True,
    )
    op.create_foreign_key(
        "fk_referrals_referrer_user_id_users",
        "referrals",
        "users",
        ["referrer_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_referrals_referred_user_id_users",
        "referrals",
        "users",
        ["referred_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_referrals_referred_user_id_users", "referrals", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_referrals_referrer_user_id_users", "referrals", type_="foreignkey"
    )
    op.drop_index("ix_referrals_referred_user_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_user_id", table_name="referrals")
    op.drop_table("referrals")
