"""create promo codes

Revision ID: 20260208_create_promo_codes
Revises: 20260208_add_free_channel_bonus_flags
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260208_create_promo_codes"
down_revision = "20260208_add_free_channel_bonus_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("bonus_photo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bonus_video", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_promo_codes_code", "promo_codes", ["code"], unique=True)
    op.alter_column("promo_codes", "bonus_photo", server_default=None)
    op.alter_column("promo_codes", "bonus_video", server_default=None)
    op.alter_column("promo_codes", "max_uses", server_default=None)
    op.alter_column("promo_codes", "used_count", server_default=None)

    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("promo_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["promo_id"], ["promo_codes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("promo_id", "user_id", name="uq_promo_redemption"),
    )
    op.create_index(
        "ix_promo_redemptions_promo_id", "promo_redemptions", ["promo_id"]
    )
    op.create_index(
        "ix_promo_redemptions_user_id", "promo_redemptions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_promo_redemptions_user_id", table_name="promo_redemptions")
    op.drop_index("ix_promo_redemptions_promo_id", table_name="promo_redemptions")
    op.drop_table("promo_redemptions")

    op.drop_index("ix_promo_codes_code", table_name="promo_codes")
    op.drop_table("promo_codes")
