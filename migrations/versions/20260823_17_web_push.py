"""Add self-hosted Web Push subscriptions and VAPID keys.

Revision ID: 20260823_17
Revises: 20260813_16
"""

from alembic import op
import sqlalchemy as sa


revision = '20260823_17'
down_revision = '20260813_16'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('global_settings', sa.Column('vapid_private_key', sa.Text(), nullable=True))
    op.add_column('global_settings', sa.Column('vapid_public_key', sa.String(length=255), nullable=True))
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.String(length=2048), nullable=False),
        sa.Column('p256dh', sa.String(length=255), nullable=False),
        sa.Column('auth', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    op.create_index('ix_push_subscriptions_user_id', 'push_subscriptions', ['user_id'])


def downgrade():
    op.drop_index('ix_push_subscriptions_user_id', table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
    op.drop_column('global_settings', 'vapid_public_key')
    op.drop_column('global_settings', 'vapid_private_key')
