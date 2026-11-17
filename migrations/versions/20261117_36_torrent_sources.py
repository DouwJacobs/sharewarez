"""Add private torrent source attachments.

Revision ID: 20261117_36
Revises: 20261106_35
"""
from alembic import op
import sqlalchemy as sa

revision = '20261117_36'
down_revision = '20261106_35'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'candidate_game_uuid' not in {column['name'] for column in inspector.get_columns('unmatched_folders')}:
        op.add_column('unmatched_folders', sa.Column('candidate_game_uuid', sa.String(36), nullable=True))
    if not any(fk['constrained_columns'] == ['candidate_game_uuid'] for fk in inspector.get_foreign_keys('unmatched_folders')):
        op.create_foreign_key('fk_unmatched_candidate_game', 'unmatched_folders', 'games',
                          ['candidate_game_uuid'], ['uuid'], ondelete='SET NULL')
    if 'game_torrent_sources' in inspector.get_table_names():
        return  # Current model metadata may already exist with the preceding stamp.
    op.create_table(
        'game_torrent_sources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('game_uuid', sa.String(36), sa.ForeignKey('games.uuid', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('label', sa.String(160), nullable=False),
        sa.Column('magnet_uri', sa.Text()),
        sa.Column('storage_key', sa.String(64)),
        sa.Column('original_filename', sa.String(255)),
        sa.Column('info_hash_v1', sa.String(40)),
        sa.Column('info_hash_v2', sa.String(64)),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('file_sha256', sa.String(64)),
        sa.Column('file_bytes', sa.BigInteger()),
        sa.Column('payload_bytes', sa.BigInteger()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.UniqueConstraint('game_uuid', 'fingerprint', name='uq_game_torrent_fingerprint'),
        sa.CheckConstraint("kind IN ('magnet', 'torrent')", name='ck_torrent_kind'),
        sa.CheckConstraint("(kind = 'magnet' AND magnet_uri IS NOT NULL AND storage_key IS NULL) OR "
                           "(kind = 'torrent' AND magnet_uri IS NULL AND storage_key IS NOT NULL)", name='ck_torrent_content'),
        sa.CheckConstraint('payload_bytes IS NULL OR payload_bytes >= 0', name='ck_torrent_payload'),
        sa.CheckConstraint('length(trim(label)) > 0', name='ck_torrent_label'),
        sa.CheckConstraint('info_hash_v1 IS NOT NULL OR info_hash_v2 IS NOT NULL', name='ck_torrent_hash'),
        sa.CheckConstraint("kind != 'torrent' OR (file_bytes IS NOT NULL AND file_bytes > 0 AND file_bytes <= 10485760 AND file_sha256 IS NOT NULL)", name='ck_torrent_file'),
    )
    for column in ('game_uuid', 'info_hash_v1', 'info_hash_v2'):
        op.create_index('ix_game_torrent_sources_' + column, 'game_torrent_sources', [column])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM game_torrent_sources')).scalar():
        raise RuntimeError('Export and remove torrent sources before downgrading.')
    op.drop_table('game_torrent_sources')
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys('unmatched_folders'):
        if foreign_key['constrained_columns'] == ['candidate_game_uuid']:
            op.drop_constraint(foreign_key['name'], 'unmatched_folders', type_='foreignkey')
    op.drop_column('unmatched_folders', 'candidate_game_uuid')
