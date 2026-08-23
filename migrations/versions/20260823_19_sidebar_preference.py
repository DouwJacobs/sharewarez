"""Persist the desktop sidebar preference.

Revision ID: 20260823_19
Revises: 20260823_18
"""

from alembic import op
import sqlalchemy as sa


revision = '20260823_19'
down_revision = '20260823_18'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_preferences',
        sa.Column('sidebar_collapsed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('user_preferences', 'sidebar_collapsed', server_default=None)


def downgrade():
    op.drop_column('user_preferences', 'sidebar_collapsed')
