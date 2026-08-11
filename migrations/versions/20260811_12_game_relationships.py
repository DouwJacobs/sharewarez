"""Add game relationships and series groups.

Revision ID: 20260811_12
Revises: 20260811_11
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_12'
down_revision = '20260811_11'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('group_type', sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_id', 'group_type', name='uq_game_group_identity'),
    )
    op.create_index('ix_game_groups_group_type', 'game_groups', ['group_type'])
    op.create_table(
        'game_relationships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game_uuid', sa.String(length=36), nullable=False),
        sa.Column('related_game_uuid', sa.String(length=36), nullable=True),
        sa.Column('related_igdb_id', sa.Integer(), nullable=False),
        sa.Column('related_name', sa.String(length=255), nullable=False),
        sa.Column('relationship_type', sa.String(length=40), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['game_uuid'], ['games.uuid'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['related_game_uuid'], ['games.uuid'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_uuid', 'related_igdb_id', 'relationship_type', 'provider', name='uq_game_relationship_identity'),
    )
    op.create_index('ix_game_relationships_game_uuid', 'game_relationships', ['game_uuid'])
    op.create_index('ix_game_relationships_related_game_uuid', 'game_relationships', ['related_game_uuid'])
    op.create_index('ix_game_relationships_related_igdb_id', 'game_relationships', ['related_igdb_id'])
    op.create_index('ix_game_relationships_relationship_type', 'game_relationships', ['relationship_type'])
    op.create_table(
        'game_group_memberships',
        sa.Column('game_uuid', sa.String(length=36), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['game_uuid'], ['games.uuid'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['game_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('game_uuid', 'group_id'),
    )


def downgrade():
    op.drop_table('game_group_memberships')
    op.drop_index('ix_game_relationships_relationship_type', table_name='game_relationships')
    op.drop_index('ix_game_relationships_related_igdb_id', table_name='game_relationships')
    op.drop_index('ix_game_relationships_related_game_uuid', table_name='game_relationships')
    op.drop_index('ix_game_relationships_game_uuid', table_name='game_relationships')
    op.drop_table('game_relationships')
    op.drop_index('ix_game_groups_group_type', table_name='game_groups')
    op.drop_table('game_groups')
