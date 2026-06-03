"""add agent billing fields

Revision ID: 20260602_add_agent_billing_fields
Revises: 20260601_create_agent_tables
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260602_add_agent_billing_fields"
down_revision = "20260601_create_agent_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "free_agent_requests_used_today",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("free_agent_requests_day", sa.String(length=10), nullable=True),
    )
    op.create_index(
        "ix_users_free_agent_requests_day",
        "users",
        ["free_agent_requests_day"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_free_agent_requests_day", table_name="users")
    op.drop_column("users", "free_agent_requests_day")
    op.drop_column("users", "free_agent_requests_used_today")
