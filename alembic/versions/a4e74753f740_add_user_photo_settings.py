"""add user photo settings

Revision ID: a4e74753f740
Revises:
Create Date: 2026-01-09 09:50:58.041622+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4e74753f740'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tg_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('subscription_active', sa.Boolean(), nullable=False),
        sa.Column('subscription_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('generations_left', sa.Integer(), nullable=False),
        sa.Column('generated_photos', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_tg_id'), 'users', ['tg_id'], unique=True)

    op.create_table(
        'user_photo_settings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('size', sa.String(length=32), nullable=False),
        sa.Column('fmt', sa.String(length=16), nullable=False),
        sa.Column('quality', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_user_photo_settings_user_id'),
    )
    op.create_index(op.f('ix_user_photo_settings_user_id'), 'user_photo_settings', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_photo_settings_user_id'), table_name='user_photo_settings')
    op.drop_table('user_photo_settings')
    op.drop_index(op.f('ix_users_tg_id'), table_name='users')
    op.drop_table('users')
