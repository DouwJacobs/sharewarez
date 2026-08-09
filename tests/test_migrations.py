from unittest.mock import patch

from sharewarez.init_manager import InitializationManager
from sharewarez.utils.migrations import current_revision, upgrade_database


BASELINE_REVISION = '20260809_01'


def test_alembic_baseline_upgrade_is_idempotent(app):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']

    upgrade_database(database_uri)
    assert current_revision(database_uri) == BASELINE_REVISION

    upgrade_database(database_uri)
    assert current_revision(database_uri) == BASELINE_REVISION


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
