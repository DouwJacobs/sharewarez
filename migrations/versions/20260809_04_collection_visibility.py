"""Add collection ownership and visibility.

Revision ID: 20260809_04
Revises: 20260809_03
"""

from alembic import op
import sqlalchemy as sa

revision = '20260809_04'
down_revision = '20260809_03'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('collections', sa.Column('visibility', sa.String(length=10), nullable=False, server_default='shared'))
    op.add_column('collections', sa.Column('owner_id', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_collections_visibility', 'collections', "visibility IN ('shared', 'private')")
    op.create_foreign_key('fk_collections_owner_id', 'collections', 'users', ['owner_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_collections_visibility', 'collections', ['visibility'], unique=False)
    op.create_index('ix_collections_owner_id', 'collections', ['owner_id'], unique=False)
    op.alter_column('collections', 'visibility', server_default=None)


def downgrade():
    op.drop_index('ix_collections_owner_id', table_name='collections')
    op.drop_index('ix_collections_visibility', table_name='collections')
    op.drop_constraint('fk_collections_owner_id', 'collections', type_='foreignkey')
    op.drop_constraint('ck_collections_visibility', 'collections', type_='check')
    op.drop_column('collections', 'owner_id')
    op.drop_column('collections', 'visibility')
