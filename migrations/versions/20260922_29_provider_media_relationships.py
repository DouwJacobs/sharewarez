"""Generalize media and relationship provider identities.

Revision ID: 20260922_29
Revises: 20260922_28
"""

from alembic import op
import sqlalchemy as sa


revision = '20260922_29'
down_revision = '20260922_28'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('game_relationships', sa.Column('related_external_id', sa.String(255)))
    op.execute(sa.text(
        "UPDATE game_relationships SET related_external_id = related_igdb_id::text"
    ))
    op.alter_column('game_relationships', 'related_external_id', nullable=False)
    op.alter_column('game_relationships', 'related_igdb_id', nullable=True)
    op.drop_constraint('uq_game_relationship_identity', 'game_relationships', type_='unique')
    op.create_unique_constraint(
        'uq_game_relationship_identity', 'game_relationships',
        ['game_uuid', 'related_external_id', 'relationship_type', 'provider'],
    )
    op.create_index(
        'ix_game_relationships_related_external_id',
        'game_relationships', ['related_external_id'],
    )
    op.alter_column(
        'game_groups', 'provider_id',
        existing_type=sa.Integer(), type_=sa.String(255),
        postgresql_using='provider_id::text',
    )

    op.add_column('images', sa.Column('provider', sa.String(32), nullable=False, server_default='igdb'))
    op.add_column('images', sa.Column('provider_image_id', sa.String(255)))
    op.add_column('images', sa.Column('source_url', sa.String(2048)))
    op.execute(sa.text(
        "UPDATE images SET provider_image_id = igdb_image_id, source_url = download_url"
    ))
    op.alter_column('images', 'provider', server_default=None)


def downgrade():
    op.drop_column('images', 'source_url')
    op.drop_column('images', 'provider_image_id')
    op.drop_column('images', 'provider')
    op.alter_column(
        'game_groups', 'provider_id',
        existing_type=sa.String(255), type_=sa.Integer(),
        postgresql_using='provider_id::integer',
    )
    op.drop_index('ix_game_relationships_related_external_id', table_name='game_relationships')
    op.drop_constraint('uq_game_relationship_identity', 'game_relationships', type_='unique')
    op.create_unique_constraint(
        'uq_game_relationship_identity', 'game_relationships',
        ['game_uuid', 'related_igdb_id', 'relationship_type', 'provider'],
    )
    op.alter_column('game_relationships', 'related_igdb_id', nullable=False)
    op.drop_column('game_relationships', 'related_external_id')
