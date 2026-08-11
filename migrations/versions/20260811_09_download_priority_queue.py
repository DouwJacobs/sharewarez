"""Add priority-aware download admission queue.

Revision ID: 20260811_09
Revises: 20260811_08
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_09'
down_revision = '20260811_08'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'download_requests',
        sa.Column('priority', sa.SmallInteger(), nullable=False, server_default='0'),
    )
    op.create_table(
        'download_queue_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('download_request_id', sa.Integer(), nullable=True),
        sa.Column('priority', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['download_request_id'], ['download_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_download_queue_entries_user_id', 'download_queue_entries', ['user_id'])
    op.create_index('ix_download_queue_entries_download_request_id', 'download_queue_entries', ['download_request_id'])
    op.create_index('ix_download_queue_entries_expires_at', 'download_queue_entries', ['expires_at'])
    op.create_index(
        'ix_download_queue_entries_order',
        'download_queue_entries',
        ['user_id', 'priority', 'created_at', 'id'],
    )


def downgrade():
    op.drop_index('ix_download_queue_entries_order', table_name='download_queue_entries')
    op.drop_index('ix_download_queue_entries_expires_at', table_name='download_queue_entries')
    op.drop_index('ix_download_queue_entries_download_request_id', table_name='download_queue_entries')
    op.drop_index('ix_download_queue_entries_user_id', table_name='download_queue_entries')
    op.drop_table('download_queue_entries')
    op.drop_column('download_requests', 'priority')
