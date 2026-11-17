"""Retain issued torrent/magnet access events for Admin Downloads."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_38'
down_revision = '20261117_37'
branch_labels = None
depends_on = None


def upgrade():
    if 'torrent_source_accesses' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table('torrent_source_accesses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('game_uuid', sa.String(36), sa.ForeignKey('games.uuid', ondelete='SET NULL')),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('game_torrent_sources.id', ondelete='SET NULL')),
        sa.Column('user_name', sa.String(64), nullable=False),
        sa.Column('game_name', sa.Text(), nullable=False),
        sa.Column('source_label', sa.String(160), nullable=False),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('file_bytes', sa.BigInteger()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('magnet_handoff', 'torrent_file')", name='ck_torrent_access_action'),
    )
    for column in ('user_id', 'game_uuid', 'source_id', 'created_at'):
        op.create_index('ix_torrent_source_accesses_' + column, 'torrent_source_accesses', [column])


def downgrade():
    op.drop_table('torrent_source_accesses')
