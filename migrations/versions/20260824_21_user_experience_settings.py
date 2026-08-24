"""Add account-scoped experience settings.

Revision ID: 20260824_21
Revises: 20260823_20
"""

from alembic import op
import sqlalchemy as sa


revision = '20260824_21'
down_revision = '20260823_20'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_preferences',
        sa.Column('experience_settings', sa.Text(), nullable=False, server_default='{}'),
    )
    op.alter_column('user_preferences', 'experience_settings', server_default=None)


def downgrade():
    op.drop_column('user_preferences', 'experience_settings')
