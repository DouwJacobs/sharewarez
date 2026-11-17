"""Automatic torrent request permission and lookup outcomes."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_37'
down_revision = '20261117_36'
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in (
        ('users', [sa.Column('can_auto_fulfill_torrent_requests', sa.Boolean(), nullable=False, server_default=sa.false())]),
        ('game_requests', [sa.Column('torrent_lookup_status', sa.String(32)), sa.Column('torrent_lookup_message', sa.Text())]),
    ):
        existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade():
    op.drop_column('game_requests', 'torrent_lookup_message')
    op.drop_column('game_requests', 'torrent_lookup_status')
    op.drop_column('users', 'can_auto_fulfill_torrent_requests')
