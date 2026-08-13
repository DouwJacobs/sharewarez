"""Add the Featured collection artwork preference.

Revision ID: 20260813_15
Revises: 20260813_14
"""

from alembic import op
import sqlalchemy as sa


revision = '20260813_15'
down_revision = '20260813_14'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'collections',
        sa.Column(
            'featured_artwork_preference',
            sa.String(length=20),
            nullable=False,
            server_default='with_logo',
        ),
    )


def downgrade():
    op.drop_column('collections', 'featured_artwork_preference')
