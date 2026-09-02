"""Add managed resumable download archive cache.

Revision ID: 20260902_23
Revises: 20260901_22
"""

from alembic import op
import sqlalchemy as sa


revision = '20260902_23'
down_revision = '20260901_22'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'download_archives',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('cache_key', sa.String(length=64), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=False),
        sa.Column('display_name', sa.String(length=512), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False, server_default='queued'),
        sa.Column('relative_path', sa.Text(), nullable=True),
        sa.Column('source_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('archive_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bytes_written', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('sha256', sa.String(length=64), nullable=True),
        sa.Column('format_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('build_job_id', sa.String(length=36), nullable=True),
        sa.Column('failure_code', sa.String(length=64), nullable=True),
        sa.Column('failure_message', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint('source_bytes >= 0', name='ck_download_archives_source_bytes'),
        sa.CheckConstraint('archive_bytes >= 0', name='ck_download_archives_archive_bytes'),
        sa.CheckConstraint('bytes_written >= 0', name='ck_download_archives_bytes_written'),
        sa.CheckConstraint('file_count >= 0', name='ck_download_archives_file_count'),
        sa.ForeignKeyConstraint(
            ['build_job_id'], ['background_jobs.id'],
            name='fk_download_archives_build_job', ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cache_key', name='uq_download_archives_cache_key'),
    )
    op.create_index('ix_download_archives_cache_key', 'download_archives', ['cache_key'])
    op.create_index('ix_download_archives_state', 'download_archives', ['state'])
    op.create_index('ix_download_archives_last_accessed_at', 'download_archives', ['last_accessed_at'])

    op.add_column('download_requests', sa.Column('archive_id', sa.String(length=36), nullable=True))
    op.add_column(
        'download_requests',
        sa.Column('delivery_kind', sa.String(length=24), nullable=False, server_default='direct'),
    )
    op.create_index('ix_download_requests_archive_id', 'download_requests', ['archive_id'])
    op.create_foreign_key(
        'fk_download_requests_archive_id', 'download_requests', 'download_archives',
        ['archive_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('download_transfers', sa.Column('archive_id', sa.String(length=36), nullable=True))
    op.add_column('download_transfers', sa.Column('range_start', sa.BigInteger(), nullable=True))
    op.add_column('download_transfers', sa.Column('range_end', sa.BigInteger(), nullable=True))
    op.add_column('download_transfers', sa.Column('http_status', sa.SmallInteger(), nullable=True))
    op.add_column(
        'download_transfers',
        sa.Column('is_resumed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_download_transfers_archive_id', 'download_transfers', ['archive_id'])
    op.create_foreign_key(
        'fk_download_transfers_archive_id', 'download_transfers', 'download_archives',
        ['archive_id'], ['id'], ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_download_transfers_archive_id', 'download_transfers', type_='foreignkey')
    op.drop_index('ix_download_transfers_archive_id', table_name='download_transfers')
    op.drop_column('download_transfers', 'is_resumed')
    op.drop_column('download_transfers', 'http_status')
    op.drop_column('download_transfers', 'range_end')
    op.drop_column('download_transfers', 'range_start')
    op.drop_column('download_transfers', 'archive_id')

    op.drop_constraint('fk_download_requests_archive_id', 'download_requests', type_='foreignkey')
    op.drop_index('ix_download_requests_archive_id', table_name='download_requests')
    op.drop_column('download_requests', 'delivery_kind')
    op.drop_column('download_requests', 'archive_id')

    op.drop_index('ix_download_archives_last_accessed_at', table_name='download_archives')
    op.drop_index('ix_download_archives_state', table_name='download_archives')
    op.drop_index('ix_download_archives_cache_key', table_name='download_archives')
    op.drop_table('download_archives')
