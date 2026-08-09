import sqlalchemy as sa

from sharewarez.models import GlobalSettings
from sharewarez.utils.secrets import decrypt_secret, encrypt_secret


def test_secret_round_trip(app):
    with app.app_context():
        encrypted = encrypt_secret('integration-secret')
        assert encrypted.startswith('enc:v1:')
        assert 'integration-secret' not in encrypted
        assert decrypt_secret(encrypted) == 'integration-secret'


def test_legacy_plaintext_remains_readable(app):
    with app.app_context():
        assert decrypt_secret('legacy-value') == 'legacy-value'


def test_global_settings_persists_ciphertext(app, db_session):
    settings = GlobalSettings(
        discord_webhook_url='https://discord.example/webhook-secret',
        smtp_password='smtp-secret',
        igdb_client_secret='igdb-secret',
    )
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)

    assert settings.smtp_password == 'smtp-secret'
    raw = db_session.execute(sa.text(
        'SELECT discord_webhook_url, smtp_password, igdb_client_secret '
        'FROM global_settings WHERE id=:id'
    ), {'id': settings.id}).mappings().one()
    assert raw['discord_webhook_url'].startswith('enc:v1:')
    assert raw['smtp_password'].startswith('enc:v1:')
    assert raw['igdb_client_secret'].startswith('enc:v1:')
    assert 'smtp-secret' not in raw['smtp_password']
