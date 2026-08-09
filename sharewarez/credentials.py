"""Offline credential-key rotation for encrypted integration settings."""

import os

from sqlalchemy import text

from sharewarez import create_app, db
from sharewarez.utils.secrets import decrypt_secret, encrypt_secret


_COLUMNS = ('discord_webhook_url', 'smtp_password', 'igdb_client_secret')


def rotate_credentials(app, old_key, new_key):
    """Atomically re-encrypt all integration credentials with new key material."""
    if not old_key or not new_key:
        raise ValueError('Both old and new credential encryption keys are required')
    if old_key == new_key:
        raise ValueError('Old and new credential encryption keys must differ')

    with app.app_context(), db.engine.begin() as connection:
        rows = list(connection.execute(text(
            'SELECT id, discord_webhook_url, smtp_password, igdb_client_secret '
            'FROM global_settings'
        )).mappings())
        for row in rows:
            values = {
                column: encrypt_secret(decrypt_secret(row[column], old_key), new_key)
                for column in _COLUMNS
            }
            connection.execute(text(
                'UPDATE global_settings SET discord_webhook_url=:discord_webhook_url, '
                'smtp_password=:smtp_password, igdb_client_secret=:igdb_client_secret '
                'WHERE id=:id'
            ), {'id': row['id'], **values})
    return len(rows)


def main():
    old_key = os.getenv('OLD_CREDENTIAL_ENCRYPTION_KEY')
    new_key = os.getenv('NEW_CREDENTIAL_ENCRYPTION_KEY')
    count = rotate_credentials(create_app(), old_key, new_key)
    print(f'Rotated integration credentials for {count} settings row(s).')


if __name__ == '__main__':
    main()
