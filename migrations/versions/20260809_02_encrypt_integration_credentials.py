"""Encrypt persisted integration credentials.

Revision ID: 20260809_02
Revises: 20260809_01
"""

from alembic import op
import sqlalchemy as sa

from sharewarez.utils.secrets import decrypt_secret, encrypt_secret


revision = '20260809_02'
down_revision = '20260809_01'
branch_labels = None
depends_on = None


_COLUMNS = ('discord_webhook_url', 'smtp_password', 'igdb_client_secret')


def _length(column):
    return 512 if column == 'discord_webhook_url' else 255


def upgrade():
    for column in _COLUMNS:
        op.alter_column(
            'global_settings', column,
            existing_type=sa.String(length=_length(column)),
            type_=sa.Text(), existing_nullable=True,
        )

    connection = op.get_bind()
    rows = list(connection.execute(sa.text(
        'SELECT id, discord_webhook_url, smtp_password, igdb_client_secret '
        'FROM global_settings'
    )).mappings())
    for row in rows:
        values = {column: encrypt_secret(row[column]) for column in _COLUMNS}
        connection.execute(
            sa.text(
                'UPDATE global_settings SET discord_webhook_url=:discord_webhook_url, '
                'smtp_password=:smtp_password, igdb_client_secret=:igdb_client_secret '
                'WHERE id=:id'
            ),
            {'id': row['id'], **values},
        )


def downgrade():
    connection = op.get_bind()
    rows = list(connection.execute(sa.text(
        'SELECT id, discord_webhook_url, smtp_password, igdb_client_secret '
        'FROM global_settings'
    )).mappings())
    for row in rows:
        values = {column: decrypt_secret(row[column]) for column in _COLUMNS}
        connection.execute(
            sa.text(
                'UPDATE global_settings SET discord_webhook_url=:discord_webhook_url, '
                'smtp_password=:smtp_password, igdb_client_secret=:igdb_client_secret '
                'WHERE id=:id'
            ),
            {'id': row['id'], **values},
        )

    for column in reversed(_COLUMNS):
        op.alter_column(
            'global_settings', column,
            existing_type=sa.Text(),
            type_=sa.String(length=_length(column)),
            existing_nullable=True,
        )
