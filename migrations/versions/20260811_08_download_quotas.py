"""Track delivered bytes and per-user monthly download quotas.

Revision ID: 20260811_08
Revises: 20260811_07
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_08'
down_revision = '20260811_07'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('monthly_download_quota_bytes', sa.BigInteger(), nullable=True))
    op.create_table(
        'download_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('download_request_id', sa.Integer(), nullable=True),
        sa.Column('filename', sa.String(length=512), nullable=False),
        sa.Column('reserved_bytes', sa.BigInteger(), nullable=False),
        sa.Column('bytes_sent', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['download_request_id'], ['download_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_download_transfers_user_id', 'download_transfers', ['user_id'])
    op.create_index('ix_download_transfers_status', 'download_transfers', ['status'])
    op.create_index('ix_download_transfers_started_at', 'download_transfers', ['started_at'])


def downgrade():
    op.drop_index('ix_download_transfers_started_at', table_name='download_transfers')
    op.drop_index('ix_download_transfers_status', table_name='download_transfers')
    op.drop_index('ix_download_transfers_user_id', table_name='download_transfers')
    op.drop_table('download_transfers')
    op.drop_column('users', 'monthly_download_quota_bytes')
