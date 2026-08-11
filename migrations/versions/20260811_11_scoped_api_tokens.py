"""Add hashed scoped API tokens.

Revision ID: 20260811_11
Revises: 20260811_10
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_11'
down_revision = '20260811_10'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('prefix'),
    )
    op.create_index('ix_api_tokens_user_id', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_prefix', 'api_tokens', ['prefix'])
    op.create_index('ix_api_tokens_expires_at', 'api_tokens', ['expires_at'])
    op.create_index('ix_api_tokens_revoked_at', 'api_tokens', ['revoked_at'])


def downgrade():
    op.drop_index('ix_api_tokens_revoked_at', table_name='api_tokens')
    op.drop_index('ix_api_tokens_expires_at', table_name='api_tokens')
    op.drop_index('ix_api_tokens_prefix', table_name='api_tokens')
    op.drop_index('ix_api_tokens_user_id', table_name='api_tokens')
    op.drop_table('api_tokens')
