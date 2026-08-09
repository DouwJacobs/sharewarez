"""Add collection grouping and artwork.

Revision ID: 20260809_03
Revises: 20260809_02
"""

from alembic import op
import sqlalchemy as sa

revision = '20260809_03'
down_revision = '20260809_02'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('collections', sa.Column('artwork_url', sa.String(length=1024), nullable=True))
    op.add_column('collections', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_collections_parent_id', 'collections', 'collections', ['parent_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_collections_parent_id', 'collections', ['parent_id'], unique=False)


def downgrade():
    op.drop_index('ix_collections_parent_id', table_name='collections')
    op.drop_constraint('fk_collections_parent_id', 'collections', type_='foreignkey')
    op.drop_column('collections', 'parent_id')
    op.drop_column('collections', 'artwork_url')
