"""Add download expiration and transfer activity tracking.

Revision ID: 20260811_10
Revises: 20260811_09
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_10'
down_revision = '20260811_09'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('download_requests', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_download_requests_expires_at', 'download_requests', ['expires_at'])
    op.execute("UPDATE download_requests SET expires_at = request_time + INTERVAL '7 days' WHERE request_time IS NOT NULL")

    op.add_column('download_transfers', sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE download_transfers SET last_activity_at = COALESCE(ended_at, started_at, NOW())")
    op.alter_column('download_transfers', 'last_activity_at', nullable=False)
    op.create_index('ix_download_transfers_last_activity_at', 'download_transfers', ['last_activity_at'])


def downgrade():
    op.drop_index('ix_download_transfers_last_activity_at', table_name='download_transfers')
    op.drop_column('download_transfers', 'last_activity_at')
    op.drop_index('ix_download_requests_expires_at', table_name='download_requests')
    op.drop_column('download_requests', 'expires_at')
