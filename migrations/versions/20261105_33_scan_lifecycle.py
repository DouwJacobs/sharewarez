"""Link durable scan attempts and preserve their terminal outcomes.

Revision ID: 20261105_33
Revises: 20260925_32
"""
from alembic import op
import sqlalchemy as sa

revision = '20261105_33'
down_revision = '20260925_32'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {column['name'] for column in inspector.get_columns('scan_jobs')}
    columns = [
        sa.Column('outcome', sa.String(20), nullable=True),
        sa.Column('folders_unmatched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('scan_options', sa.Text(), nullable=True),
        sa.Column('background_job_id', sa.String(36), nullable=True),
        sa.Column('replacement_job_id', sa.String(36), nullable=True),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column('scan_jobs', column)
    # Metadata-created installs already have these objects under PostgreSQL's
    # generated names. Compare their columns rather than requiring a name.
    foreign_keys = inspector.get_foreign_keys('scan_jobs')
    for column, name in [('background_job_id', 'fk_scan_background_job'), ('replacement_job_id', 'fk_scan_replacement_job')]:
        if not any(fk['constrained_columns'] == [column] for fk in foreign_keys):
            op.create_foreign_key(name, 'scan_jobs', 'background_jobs', [column], ['id'], ondelete='SET NULL')
    if 'ix_scan_jobs_background_job_id' not in {index['name'] for index in inspector.get_indexes('scan_jobs')}:
        op.create_index('ix_scan_jobs_background_job_id', 'scan_jobs', ['background_job_id'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    op.drop_index('ix_scan_jobs_background_job_id', table_name='scan_jobs')
    for fk in inspector.get_foreign_keys('scan_jobs'):
        if fk['constrained_columns'] in (['background_job_id'], ['replacement_job_id']):
            op.drop_constraint(fk['name'], 'scan_jobs', type_='foreignkey')
    for name in ('replacement_job_id', 'background_job_id', 'scan_options', 'folders_unmatched', 'outcome'):
        op.drop_column('scan_jobs', name)
