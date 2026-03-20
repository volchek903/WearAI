"""add referrals to users

Revision ID: 20260127_add_referrals
Revises: 901c4e5b3ebc
Create Date: 2026-01-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260127_add_referrals"
down_revision = "901c4e5b3ebc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referred_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "referrals_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_foreign_key(
        "fk_users_referred_by_id_users",
        "users",
        "users",
        ["referred_by_id"],
        ["id"],
    )
    op.alter_column("users", "referrals_count", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_users_referred_by_id_users", "users", type_="foreignkey")
    op.drop_column("users", "referrals_count")
    op.drop_column("users", "referred_by_id")
