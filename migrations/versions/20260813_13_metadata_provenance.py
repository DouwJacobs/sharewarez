"""Add game metadata provenance and provider candidates.

Revision ID: 20260813_13
Revises: 20260811_12
"""

from alembic import op
import sqlalchemy as sa


revision = '20260813_13'
down_revision = '20260811_12'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('games', sa.Column('metadata_provenance', sa.JSON(), nullable=True))
    op.add_column('games', sa.Column('metadata_provider_values', sa.JSON(), nullable=True))
    op.execute("UPDATE games SET metadata_provenance = '{}', metadata_provider_values = '{}'")
    op.alter_column('games', 'metadata_provenance', nullable=False)
    op.alter_column('games', 'metadata_provider_values', nullable=False)


def downgrade():
    op.drop_column('games', 'metadata_provider_values')
    op.drop_column('games', 'metadata_provenance')
