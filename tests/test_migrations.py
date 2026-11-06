import hashlib
import json
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


def test_scan_lifecycle_upgrade_preserves_previous_rows(app, db_session):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.downgrade(alembic_config(database_uri), '20260925_32')
    db_session.execute(text("INSERT INTO scan_jobs (id, status, folders_success, folders_failed) VALUES ('legacy-scan', 'Failed', 2, 1)"))
    db_session.commit()
    command.upgrade(alembic_config(database_uri), 'head')
    row = db_session.execute(text("SELECT status, folders_success, folders_failed, folders_unmatched, outcome, background_job_id, replacement_job_id FROM scan_jobs WHERE id = 'legacy-scan'" )).one()
    assert tuple(row) == ('Failed', 2, 1, 0, None, None, None)
    assert current_revision(database_uri) == head_revision()


def test_scan_lifecycle_fresh_bootstrap_matches_head(app, db_session):
    from sharewarez.models import ScanJob
    row = ScanJob(status='Completed', outcome='completed', scan_options={'fetch_hltb': False})
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.folders_unmatched == 0 and row.scan_options == {'fetch_hltb': False}
    assert current_revision(app.config['SQLALCHEMY_DATABASE_URI']) == head_revision() == '20261106_35'


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


def test_provider_identity_migration_backfills_existing_igdb_rows(app, db_session):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.downgrade(alembic_config(database_uri), '20260905_25')

    db_session.execute(text(
        "INSERT INTO libraries (uuid, name, platform, display_order) VALUES "
        "('00000000-0000-0000-0000-000000000026', 'Migration Library', "
        "'PCWIN', 0)"
    ))
    db_session.execute(text(
        "INSERT INTO games "
        "(uuid, igdb_id, name, url_igdb, library_uuid, size, "
        "metadata_provenance, metadata_provider_values) VALUES "
        "('10000000-0000-0000-0000-000000000026', 26001, 'Migrated Game', "
        "'https://www.igdb.com/games/migrated-game', "
        "'00000000-0000-0000-0000-000000000026', 0, '{}', '{}')"
    ))
    db_session.execute(text(
        "INSERT INTO game_requests "
        "(request_type, igdb_id, parent_igdb_id, game_name, status, "
        "created_at, updated_at) VALUES "
        "('new_game', 26002, 26001, 'Requested Game', 'pending', now(), now())"
    ))
    db_session.execute(text(
        "INSERT INTO global_settings (settings, last_updated) VALUES ('{}', now())"
    ))
    db_session.commit()

    upgrade_database(database_uri)

    identity = db_session.execute(text(
        "SELECT provider, external_id, canonical, provider_url "
        "FROM game_external_identities WHERE game_uuid = "
        "'10000000-0000-0000-0000-000000000026'"
    )).one()
    assert identity == (
        'igdb',
        '26001',
        True,
        'https://www.igdb.com/games/migrated-game',
    )
    request_identity = db_session.execute(text(
        "SELECT metadata_provider, provider_game_id, provider_parent_id "
        "FROM game_requests WHERE igdb_id = 26002"
    )).one()
    assert request_identity == ('igdb', '26002', '26001')
    provider_settings = db_session.execute(text(
        "SELECT rawg_enabled, metadata_provider_order FROM global_settings "
        "ORDER BY id DESC LIMIT 1"
    )).one()
    assert provider_settings == (False, ['igdb'])


def test_secure_invitation_migration_preserves_existing_links(app, db_session):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.downgrade(alembic_config(database_uri), '20260922_29')
    raw_token = 'legacy-link-that-was-already-delivered'
    creator_id = '00000000-0000-0000-0000-000000000030'
    db_session.execute(text(
        "INSERT INTO users (name, email, password_hash, role, state, user_id) VALUES "
        "('migration_admin', 'migration-admin@example.com', 'hash', 'admin', true, :user_id)"
    ), {'user_id': creator_id})
    db_session.execute(text(
        "INSERT INTO invite_tokens (token, creator_user_id, created_at, expires_at, used) "
        "VALUES (:token, :creator, now(), now() + interval '7 days', false)"
    ), {'token': raw_token, 'creator': creator_id})
    db_session.commit()

    upgrade_database(database_uri)

    stored = db_session.execute(text(
        'SELECT token_digest, revoked_at, revoked_by_user_id FROM invite_tokens'
    )).one()
    assert stored.token_digest == hashlib.sha256(raw_token.encode()).hexdigest()
    assert stored.revoked_at is None
    assert stored.revoked_by_user_id is None


def test_notification_delivery_migration_preserves_effective_preferences(app, db_session):
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.downgrade(alembic_config(database_uri), '20260923_30')
    db_session.execute(text(
        "INSERT INTO users (name, email, password_hash, role, state, user_id) VALUES "
        "('notification_migration', 'notification-migration@example.com', 'hash', "
        "'user', true, '00000000-0000-0000-0000-000000000031')"
    ))
    user_id = db_session.execute(text(
        "SELECT id FROM users WHERE name = 'notification_migration'"
    )).scalar_one()
    db_session.execute(text(
        'INSERT INTO user_preferences '
        '(user_id, saved_searches, sidebar_collapsed, experience_settings) '
        "VALUES (:user_id, '[]', false, :settings)"
    ), {
        'user_id': user_id,
        'settings': json.dumps({'notifications': {
            'requests': False, 'issues': True, 'downloads': True,
            'games': True, 'browser': False,
        }}),
    })
    db_session.execute(text(
        "INSERT INTO global_settings "
        "(settings, last_updated, discord_notify_new_games, "
        "discord_notify_game_updates, discord_notify_downloads) VALUES "
        "(:settings, now(), true, false, false)"
    ), {'settings': json.dumps({
        'notifyRequesterRequestEmail': True,
        'notifyAdminRequestEmail': False,
        'notifyAdminIssueEmail': True,
        'notifyReporterIssueEmail': False,
        'notifyAdminDownloadCancellations': False,
        'notifyAdminRepeatDownloads': True,
    })})
    db_session.commit()

    upgrade_database(database_uri)

    experience = json.loads(db_session.execute(text(
        'SELECT experience_settings FROM user_preferences WHERE user_id = :user_id'
    ), {'user_id': user_id}).scalar_one())
    events = experience['notifications']['events']
    assert events['request_updated'] == {'in_app': False, 'email': True, 'push': False}
    assert events['issue_comment'] == {'in_app': True, 'email': True, 'push': False}
    values = json.loads(db_session.execute(text(
        'SELECT settings FROM global_settings ORDER BY id DESC LIMIT 1'
    )).scalar_one())
    policy = values['notificationPolicy']
    assert policy['new_game']['discord'] is True
    assert policy['request_updated']['email'] is True
    assert policy['download_cancelled']['in_app'] is False
    assert policy['download_repeated']['in_app'] is True


def test_latest_upgrades_reconcile_metadata_created_schema(app, db_session):
    """A metadata-created schema may carry an older compatible stamp."""
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    settings = GlobalSettings(
        settings={}, local_metadata_filename='sharewarez.json'
    )
    db_session.add(settings)
    db_session.commit()
    command.stamp(alembic_config(database_uri), '20260923_30', purge=True)

    upgrade_database(database_uri)

    assert current_revision(database_uri) == head_revision()
    db_session.refresh(settings)
    assert settings.local_metadata_filename == 'sharewarez.json'
    column_default = db_session.execute(text(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'global_settings' "
        "AND column_name = 'local_metadata_filename'"
    )).scalar_one()
    assert 'gamelibrary.json' in column_default
    tables = set(db_session.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )).scalars())
    assert {'notification_events', 'webhook_endpoints', 'webhook_deliveries'} <= tables


def test_transfer_evidence_upgrade_preserves_populated_previous_schema(app, db_session):
    from uuid import uuid4
    from sharewarez.models import DownloadTransfer, User
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.downgrade(alembic_config(uri), '20261105_33')
    owner = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', password_hash='unused', role='user')
    actor = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', password_hash='unused', role='admin')
    db_session.add_all([owner, actor])
    db_session.commit()
    transfer_id = db_session.execute(text("INSERT INTO download_transfers (user_id, filename, reserved_bytes, bytes_sent, status, started_at, last_activity_at, is_resumed) VALUES (:owner, 'legacy.bin', 7, 7, 'interrupted', now(), now(), false) RETURNING id"), {'owner': owner.id}).scalar_one()
    db_session.commit()
    command.upgrade(alembic_config(uri), 'head')
    row = db_session.get(DownloadTransfer, transfer_id)
    assert row.bytes_sent == row.reserved_bytes == 7 and row.status == 'interrupted'
    assert all(getattr(row, field) is None for field in ('end_reason', 'delivery_kind', 'expected_response_bytes', 'correlation_id', 'ended_by_user_id', 'last_progress_at'))
    assert row.end_reason_label == 'Reason unavailable'
    row.end_reason = 'admin_stop'
    row.ended_by_user_id = actor.id
    row.expected_response_bytes = 8_000_000_000
    db_session.commit()
    db_session.delete(actor)
    db_session.commit()
    db_session.refresh(row)
    assert row.ended_by_user_id is None and row.expected_response_bytes == 8_000_000_000
    db_session.commit()
    command.downgrade(alembic_config(uri), '20261105_33')
    command.upgrade(alembic_config(uri), 'head')
    assert current_revision(uri) == head_revision() == '20261106_35'


def test_transfer_evidence_upgrade_accepts_metadata_created_columns(app, db_session):
    from sqlalchemy import inspect
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.stamp(alembic_config(uri), '20261105_33', purge=True)
    command.upgrade(alembic_config(uri), 'head')
    command.upgrade(alembic_config(uri), 'head')
    columns = {column['name']: column for column in inspect(db.engine).get_columns('download_transfers')}
    assert columns['last_progress_at']['type'].timezone
    assert columns['end_reason']['nullable'] and columns['expected_response_bytes']['nullable']
    assert len([fk for fk in inspect(db.engine).get_foreign_keys('download_transfers') if fk['constrained_columns'] == ['ended_by_user_id']]) == 1


def test_hide_history_upgrade_retains_accounting_and_downgrade(app, db_session):
    from uuid import uuid4
    from sharewarez.models import DownloadTransfer, User
    from sqlalchemy import inspect
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    command.downgrade(alembic_config(uri), '20261106_34')
    owner = User(name=uuid4().hex, email=uuid4().hex + '@example.test', password_hash='unused', role='user')
    db_session.add(owner); db_session.commit()
    transfer_id = db_session.execute(text("INSERT INTO download_transfers (user_id, filename, reserved_bytes, bytes_sent, status, started_at, last_activity_at, is_resumed, end_reason) VALUES (:owner, 'retained.bin', 123, 123, 'interrupted', now(), now(), false, 'peer_disconnect') RETURNING id"), {'owner': owner.id}).scalar_one()
    db_session.commit()
    command.upgrade(alembic_config(uri), 'head')
    row = db_session.get(DownloadTransfer, transfer_id)
    assert row.admin_history_hidden_at is None and row.reserved_bytes == 123 and row.end_reason == 'peer_disconnect'
    db_session.commit()
    command.downgrade(alembic_config(uri), '20261106_34')
    assert 'admin_history_hidden_at' not in {column['name'] for column in inspect(db.engine).get_columns('download_transfers')}
    command.upgrade(alembic_config(uri), 'head')
    command.upgrade(alembic_config(uri), 'head')
    assert db_session.get(DownloadTransfer, transfer_id).reserved_bytes == 123
