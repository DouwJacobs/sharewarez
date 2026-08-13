"""add per-game image defaults

Revision ID: 20260813_16
Revises: 20260813_15
"""

from alembic import op
import sqlalchemy as sa


revision = '20260813_16'
down_revision = '20260813_15'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'images',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_images_is_default', 'images', ['is_default'], unique=False)


def downgrade():
    op.drop_index('ix_images_is_default', table_name='images')
    op.drop_column('images', 'is_default')
