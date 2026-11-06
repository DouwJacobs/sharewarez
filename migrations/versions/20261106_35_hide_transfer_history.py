"""Hide administrative history without discarding delivery/accounting evidence.

Revision ID: 20261106_35
Revises: 20261106_34
"""
from alembic import op
import sqlalchemy as sa

revision = '20261106_35'
down_revision = '20261106_34'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'admin_history_hidden_at' not in {column['name'] for column in inspector.get_columns('download_transfers')}:
        op.add_column('download_transfers', sa.Column('admin_history_hidden_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('download_transfers', 'admin_history_hidden_at')
