"""Persist the administrator's manually uploaded catalogue snapshot."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_39'
down_revision = '20261117_38'
branch_labels = None
depends_on = None


def upgrade():
    if 'uploaded_torrent_catalogues' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table('uploaded_torrent_catalogues',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('entry_count', sa.Integer(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_uploaded_catalogue_singleton'),
    )


def downgrade():
    op.drop_table('uploaded_torrent_catalogues')
