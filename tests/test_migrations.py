from unittest.mock import patch

import pytest
from alembic import command
from sqlalchemy import text

from sharewarez import db
from sharewarez.init_manager import InitializationManager
from sharewarez.models import GlobalSettings
from sharewarez.utils.migrations import (
    alembic_config,
    current_revision,
    head_revision,
    upgrade_database,
)


BASELINE_REVISION = '20260809_01'


@pytest.fixture(autouse=True)
def current_versioned_schema(app):
    """Give each migration test an isolated current schema and revision marker."""
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    with app.app_context():
        db.session.execute(text('DROP TABLE IF EXISTS alembic_version'))
        db.session.commit()
        db.drop_all()
        db.create_all()
    command.stamp(alembic_config(database_uri), 'head', purge=True)


def test_alembic_baseline_upgrade_is_idempotent(app):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']

    upgrade_database(database_uri)
    assert current_revision(database_uri) == head_revision()

    upgrade_database(database_uri)
    assert current_revision(database_uri) == head_revision()


def test_credential_migration_encrypts_legacy_plaintext(app, db_session):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.stamp(alembic_config(database_uri), BASELINE_REVISION, purge=True)
    db_session.execute(text(
        "INSERT INTO global_settings (settings, last_updated, discord_webhook_url, "
        "smtp_password, igdb_client_secret) VALUES "
        "('{}', now(), 'https://discord.example/legacy', 'smtp-legacy', 'igdb-legacy')"
    ))
    db_session.commit()

    upgrade_database(database_uri, '20260809_02')

    stored = db_session.execute(text(
        'SELECT discord_webhook_url, smtp_password, igdb_client_secret '
        'FROM global_settings ORDER BY id DESC LIMIT 1'
    )).one()
    assert all(value.startswith('enc:v1:') for value in stored)
    settings = db_session.query(GlobalSettings).order_by(GlobalSettings.id.desc()).first()
    assert settings.discord_webhook_url == 'https://discord.example/legacy'
    assert settings.smtp_password == 'smtp-legacy'
    assert settings.igdb_client_secret == 'igdb-legacy'

def test_versioned_database_skips_legacy_schema_reconciler(app, db_session):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    upgrade_database(database_uri)

    with (
        patch('sharewarez.updateschema.DatabaseManager.add_column_if_not_exists') as legacy,
        patch('sharewarez.utils.migrations.upgrade_database') as upgrade,
    ):
        assert InitializationManager()._phase2_database_structure() is True

    legacy.assert_not_called()
    upgrade.assert_called_once_with(database_uri)


def test_pending_migration_creates_pre_upgrade_backup(app, db_session, monkeypatch):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    upgrade_database(database_uri)
    monkeypatch.setenv('BACKUP_BEFORE_UPGRADE', 'true')

    with (
        patch('sharewarez.utils.migrations.database_needs_upgrade', return_value=True),
        patch('sharewarez.backups.create_backup', return_value='/backups/pre-upgrade.dump') as backup,
        patch('sharewarez.utils.migrations.upgrade_database') as upgrade,
    ):
        assert InitializationManager()._phase2_database_structure() is True

    backup.assert_called_once_with(database_uri, reason='pre-upgrade')
    upgrade.assert_called_once_with(database_uri)
