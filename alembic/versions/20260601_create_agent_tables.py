"""create agent tables

Revision ID: 20260601_create_agent_tables
Revises: 20260321_add_perf_indexes_for_start
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260601_create_agent_tables"
down_revision = "20260321_add_perf_indexes_for_start"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_agent_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("web_search_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("documents_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("deep_analysis_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("quick_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("document_session_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_user_agent_settings_user_id", "user_agent_settings", ["user_id"])
    op.create_unique_constraint(
        "uq_user_agent_settings_user_id",
        "user_agent_settings",
        ["user_id"],
    )

    op.create_table(
        "agent_message",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_message_user_id", "agent_message", ["user_id"])
    op.create_index("ix_agent_message_role", "agent_message", ["role"])
    op.create_index("ix_agent_message_created_at", "agent_message", ["created_at"])

    op.create_table(
        "agent_document",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_key", sa.String(length=64), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("text_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_document_user_id", "agent_document", ["user_id"])
    op.create_index("ix_agent_document_session_key", "agent_document", ["session_key"])
    op.create_index("ix_agent_document_created_at", "agent_document", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_document_created_at", table_name="agent_document")
    op.drop_index("ix_agent_document_session_key", table_name="agent_document")
    op.drop_index("ix_agent_document_user_id", table_name="agent_document")
    op.drop_table("agent_document")

    op.drop_index("ix_agent_message_created_at", table_name="agent_message")
    op.drop_index("ix_agent_message_role", table_name="agent_message")
    op.drop_index("ix_agent_message_user_id", table_name="agent_message")
    op.drop_table("agent_message")

    op.drop_constraint(
        "uq_user_agent_settings_user_id",
        "user_agent_settings",
        type_="unique",
    )
    op.drop_index("ix_user_agent_settings_user_id", table_name="user_agent_settings")
    op.drop_table("user_agent_settings")
