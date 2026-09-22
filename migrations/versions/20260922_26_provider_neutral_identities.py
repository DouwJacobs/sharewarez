"""Add provider-neutral game and request identities.

Revision ID: 20260922_26
Revises: 20260905_25
"""

from alembic import op
import sqlalchemy as sa


revision = '20260922_26'
down_revision = '20260905_25'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'game_external_identities' not in inspector.get_table_names():
        op.create_table(
        'game_external_identities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game_uuid', sa.String(length=36), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('canonical', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('provider_url', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            'provider = lower(provider)',
            name='ck_game_external_identity_provider_lowercase',
        ),
        sa.ForeignKeyConstraint(['game_uuid'], ['games.uuid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'game_uuid', 'provider',
            name='uq_game_external_identity_game_provider',
        ),
        sa.UniqueConstraint(
            'provider', 'external_id',
            name='uq_game_external_identity_provider',
        ),
    )
        op.create_index(
            'ix_game_external_identities_game_uuid',
            'game_external_identities', ['game_uuid'],
        )
        op.create_index(
            'uq_game_external_identity_canonical',
            'game_external_identities', ['game_uuid'], unique=True,
            postgresql_where=sa.text('canonical'),
            sqlite_where=sa.text('canonical'),
        )
    op.execute(sa.text(
        "INSERT INTO game_external_identities "
        "(game_uuid, provider, external_id, canonical, provider_url) "
        "SELECT uuid, 'igdb', CAST(igdb_id AS VARCHAR(255)), true, url_igdb "
        "FROM games WHERE igdb_id IS NOT NULL ON CONFLICT DO NOTHING"
    ))

    request_columns = {column['name'] for column in inspector.get_columns('game_requests')}
    if 'metadata_provider' not in request_columns:
        op.add_column('game_requests', sa.Column('metadata_provider', sa.String(length=32)))
    if 'provider_game_id' not in request_columns:
        op.add_column('game_requests', sa.Column('provider_game_id', sa.String(length=255)))
    if 'provider_parent_id' not in request_columns:
        op.add_column('game_requests', sa.Column('provider_parent_id', sa.String(length=255)))
    indexes = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes('game_requests')}
    if 'ix_game_requests_metadata_provider' not in indexes:
        op.create_index('ix_game_requests_metadata_provider', 'game_requests', ['metadata_provider'])
    if 'ix_game_requests_provider_game_id' not in indexes:
        op.create_index('ix_game_requests_provider_game_id', 'game_requests', ['provider_game_id'])
    op.execute(sa.text(
        "UPDATE game_requests SET "
        "metadata_provider = 'igdb', "
        "provider_game_id = CAST(igdb_id AS VARCHAR(255)), "
        "provider_parent_id = CAST(parent_igdb_id AS VARCHAR(255)) "
        "WHERE request_type = 'new_game' AND igdb_id IS NOT NULL"
    ))
    if 'uq_game_requests_new_game_provider' not in indexes:
        op.create_index(
            'uq_game_requests_new_game_provider', 'game_requests',
            ['metadata_provider', 'provider_game_id'], unique=True,
            postgresql_where=sa.text(
                "request_type = 'new_game' AND metadata_provider IS NOT NULL "
                "AND provider_game_id IS NOT NULL"
            ),
            sqlite_where=sa.text(
                "request_type = 'new_game' AND metadata_provider IS NOT NULL "
                "AND provider_game_id IS NOT NULL"
            ),
        )


def downgrade():
    op.drop_index('uq_game_requests_new_game_provider', table_name='game_requests')
    op.drop_index('ix_game_requests_provider_game_id', table_name='game_requests')
    op.drop_index('ix_game_requests_metadata_provider', table_name='game_requests')
    op.drop_column('game_requests', 'provider_parent_id')
    op.drop_column('game_requests', 'provider_game_id')
    op.drop_column('game_requests', 'metadata_provider')
    op.drop_index(
        'uq_game_external_identity_canonical',
        table_name='game_external_identities',
    )
    op.drop_index(
        'ix_game_external_identities_game_uuid',
        table_name='game_external_identities',
    )
    op.drop_table('game_external_identities')
