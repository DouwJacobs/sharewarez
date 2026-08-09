"""Add per-user saved searches.

Revision ID: 20260809_06
Revises: 20260809_05
"""

from alembic import op
import sqlalchemy as sa

revision = '20260809_06'
down_revision = '20260809_05'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user_preferences', sa.Column('saved_searches', sa.Text(), nullable=False, server_default='[]'))
    op.alter_column('user_preferences', 'saved_searches', server_default=None)


def downgrade():
    op.drop_column('user_preferences', 'saved_searches')
