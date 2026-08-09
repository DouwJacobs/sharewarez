import pytest
from sqlalchemy import text

from sharewarez.credentials import rotate_credentials
from sharewarez.utils.secrets import decrypt_secret, encrypt_secret


def _insert_credentials(db_session, key):
    values = {
        'discord': encrypt_secret('https://discord.example/rotation', key),
        'smtp': encrypt_secret('smtp-rotation', key),
        'igdb': encrypt_secret('igdb-rotation', key),
    }
    db_session.execute(text(
        'INSERT INTO global_settings (settings, last_updated, discord_webhook_url, '
        'smtp_password, igdb_client_secret) VALUES '
        "('{}', now(), :discord, :smtp, :igdb)"
    ), values)
    db_session.commit()


def test_rotate_credentials_reencrypts_every_value(app, db_session):
    _insert_credentials(db_session, 'old-key')

    assert rotate_credentials(app, 'old-key', 'new-key') == 1

    stored = db_session.execute(text(
        'SELECT discord_webhook_url, smtp_password, igdb_client_secret '
        'FROM global_settings ORDER BY id DESC LIMIT 1'
    )).one()
    assert decrypt_secret(stored.discord_webhook_url, 'new-key') == (
        'https://discord.example/rotation'
    )
    assert decrypt_secret(stored.smtp_password, 'new-key') == 'smtp-rotation'
    assert decrypt_secret(stored.igdb_client_secret, 'new-key') == 'igdb-rotation'


def test_rotate_credentials_rolls_back_on_wrong_old_key(app, db_session):
    db_session.execute(text(
        'INSERT INTO global_settings (settings, last_updated, discord_webhook_url) '
        "VALUES ('{}', now(), 'legacy-plaintext')"
    ))
    db_session.commit()
    _insert_credentials(db_session, 'actual-old-key')
    before = db_session.execute(text(
        'SELECT discord_webhook_url FROM global_settings ORDER BY id'
    )).scalars().all()

    with pytest.raises(RuntimeError, match='cannot be decrypted'):
        rotate_credentials(app, 'wrong-old-key', 'new-key')

    db_session.expire_all()
    after = db_session.execute(text(
        'SELECT discord_webhook_url FROM global_settings ORDER BY id'
    )).scalars().all()
    assert after == before


@pytest.mark.parametrize('old_key,new_key', [('', 'new'), ('old', ''), ('same', 'same')])
def test_rotate_credentials_rejects_invalid_keys(app, old_key, new_key):
    with pytest.raises(ValueError):
        rotate_credentials(app, old_key, new_key)
