"""Preserve transfer evidence without guessing historical outcomes.

Revision ID: 20261106_34
Revises: 20261105_33
"""
from alembic import op
import sqlalchemy as sa

revision = '20261106_34'
down_revision = '20261105_33'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {column['name'] for column in inspector.get_columns('download_transfers')}
    for column in [
        sa.Column('end_reason', sa.String(32), nullable=True),
        sa.Column('delivery_kind', sa.String(24), nullable=True),
        sa.Column('expected_response_bytes', sa.BigInteger(), nullable=True),
        sa.Column('correlation_id', sa.String(64), nullable=True),
        sa.Column('ended_by_user_id', sa.Integer(), nullable=True),
        sa.Column('last_progress_at', sa.DateTime(timezone=True), nullable=True),
    ]:
        if column.name not in existing:
            op.add_column('download_transfers', column)
    if not any(fk['constrained_columns'] == ['ended_by_user_id'] for fk in inspector.get_foreign_keys('download_transfers')):
        op.create_foreign_key('fk_transfer_ended_by_user', 'download_transfers', 'users', ['ended_by_user_id'], ['id'], ondelete='SET NULL')


def downgrade():
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys('download_transfers'):
        if fk['constrained_columns'] == ['ended_by_user_id']:
            op.drop_constraint(fk['name'], 'download_transfers', type_='foreignkey')
    for name in ('last_progress_at', 'ended_by_user_id', 'correlation_id', 'expected_response_bytes', 'delivery_kind', 'end_reason'):
        op.drop_column('download_transfers', name)