"""Add the per-user notification center.

Revision ID: 20260813_14
Revises: 20260813_13
"""

from alembic import op
import sqlalchemy as sa


revision = '20260813_14'
down_revision = '20260813_13'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('link_url', sa.String(length=1024), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'dedupe_key', name='uq_notification_user_event'),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_event_type', 'notifications', ['event_type'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('ix_notifications_read_at', 'notifications', ['read_at'])


def downgrade():
    op.drop_index('ix_notifications_read_at', table_name='notifications')
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_event_type', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
