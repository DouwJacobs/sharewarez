"""Regression coverage for durable request-only torrent fulfilment."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from sharewarez.models import (BackgroundJob, Game, GameRequest, GameRequestUser,
                              GlobalSettings, Library, User)
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.torrent_requests import eligible, execute_lookup, queue_lookup


@pytest.fixture
def torrent_request(db_session):
    token = uuid4().hex
    library = Library(name='Automation ' + token, platform=LibraryPlatform.PCWIN)
    user = User(name='auto_' + token[:12], email=token + '@test.invalid',
                password_hash='unused', role='user', state=True,
                can_auto_fulfill_torrent_requests=True)
    game_request = GameRequest(game_name='Automation Game ' + token, request_type='new_game',
                               status='pending', metadata_provider='rawg', provider_game_id=token)
    game_request.requesters.append(GameRequestUser(user=user))
    db_session.add_all([library, user, game_request])
    db_session.flush()
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db_session.add(settings)
    previous = dict(settings.settings or {})
    settings.settings = {**previous, 'enableGameRequests': True, 'autoFulfillTorrentRequests': True,
                         'torrentCatalogueUrls': 'https://example.com/catalogue.json',
                         'torrentDestinationLibraryUuid': library.uuid}
    db_session.commit()
    yield SimpleNamespace(request=game_request, user=user, library=library, settings=settings,
                          session=db_session)
    db_session.rollback()
    settings.settings = previous
    db_session.commit()


def context():
    return SimpleNamespace(heartbeat=Mock(), check_cancelled=Mock())


def run_lookup(case, fetch=None, match=None):
    entry = {'title': case.request.game_name, 'uris': ['magnet:?xt=urn:btih:' + 'b' * 40],
             'source_name': 'Public test catalogue', 'source_url': 'https://example.com/catalogue.json'}
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', side_effect=fetch or (lambda url: {})), \
         patch('sharewarez.utils.torrent_catalogues.match_catalogues', return_value=match or {'status': 'matched', 'entry': entry}), \
         patch('sharewarez.utils.request_notifications.notify_request_updated') as notify:
        result = execute_lookup(context(), {'request_id': case.request.id, 'user_id': case.user.id})
        return result, notify


@pytest.mark.parametrize('field,value', [('autoFulfillTorrentRequests', False), ('enableGameRequests', False)])
def test_disabled_automation_does_not_queue(torrent_request, field, value):
    case = torrent_request
    case.settings.settings = {**case.settings.settings, field: value}
    assert queue_lookup(case.request, case.user) is None


def test_new_authorized_submission_can_resume_previously_skipped_lookup(torrent_request):
    case = torrent_request
    case.request.torrent_lookup_status = 'skipped'
    case.session.commit()
    assert queue_lookup(case.request, case.user) is not None


def test_permission_defaults_to_denied_and_cannot_trigger_queue(torrent_request):
    case = torrent_request
    case.user.can_auto_fulfill_torrent_requests = False
    assert queue_lookup(case.request, case.user) is None
    denied = User(name='denied_' + uuid4().hex[:12], email=uuid4().hex + '@test.invalid',
                  password_hash='unused', role='user')
    case.session.add(denied)
    case.session.flush()
    assert denied.can_auto_fulfill_torrent_requests is False


def test_queue_is_durable_and_idempotent(torrent_request):
    case = torrent_request
    job = queue_lookup(case.request, case.user)
    assert job.task_name == 'requests.torrent_lookup'
    assert case.request.torrent_lookup_status == 'queued'
    assert queue_lookup(case.request, case.user) is None
    case.session.commit()
    assert case.session.get(BackgroundJob, job.id).payload['request_id'] == case.request.id


def test_authorized_join_queues_lookup_in_submission_transaction(torrent_request):
    from sharewarez.utils.game_requests import create_or_join_metadata_request
    case = torrent_request
    joining = User(name='joining_' + uuid4().hex[:12], email=uuid4().hex + '@test.invalid',
                   password_hash='unused', role='user', state=True,
                   can_auto_fulfill_torrent_requests=True)
    case.session.add(joining)
    case.session.commit()
    record, link = create_or_join_metadata_request(joining, 'rawg', case.request.provider_game_id)
    assert record.id == case.request.id
    assert link.user_id == joining.id
    assert record.torrent_lookup_status == 'queued'
    job = case.session.query(BackgroundJob).filter_by(task_name='requests.torrent_lookup',
        created_by_id=joining.id).one()
    assert job.payload['request_id'] == record.id


def test_admin_can_select_release_but_member_cannot(torrent_request):
    from sharewarez.utils.torrent_requests import allowed
    case = torrent_request
    entry = {'title': case.request.game_name, 'uris': ['magnet:?xt=urn:btih:' + 'e' * 40],
             'source_name': 'Public source', 'source_url': 'https://example.com/catalogue.json'}
    assert not allowed(case.request, case.user, case.settings.settings, entry)
    admin = User(name='selector_' + uuid4().hex[:12], email=uuid4().hex + '@test.invalid',
                 role='admin', state=True, password_hash='unused')
    case.session.add(admin)
    case.session.commit()
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue') as fetch, \
         patch('sharewarez.utils.request_notifications.notify_request_updated'):
        result = execute_lookup(context(), {'request_id': case.request.id, 'user_id': admin.id,
                                            'selected_entry': entry})
    fetch.assert_not_called()
    assert result['status'] == 'fulfilled'
    assert case.request.handled_by_user_id == admin.id
    assert case.request.fulfilled_game.torrent_sources[0].created_by == admin.id


def test_ambiguous_job_retains_selectable_candidates(torrent_request):
    case = torrent_request
    entry = {'title': case.request.game_name, 'uris': ['magnet:?xt=urn:btih:' + 'e' * 40],
             'source_name': 'Public source', 'source_url': 'https://example.com/catalogue.json'}
    result, _ = run_lookup(case, match={'status': 'ambiguous', 'entry': None, 'candidates': [entry]})
    assert result['candidates'] == [entry]


@pytest.mark.parametrize('enabled', [True, False])
def test_worker_applies_upload_date_setting(torrent_request, enabled):
    case = torrent_request
    case.settings.settings = {**case.settings.settings, 'torrentPreferLatestUpload': enabled}
    case.session.commit()
    source = {'name': 'Public test source', 'source_url': 'https://example.com/catalogue.json',
              'downloads': [
                  {'title': case.request.game_name + ' – v1.0', 'uploadDate': '2025-01-01',
                   'uris': ['magnet:?xt=urn:btih:' + 'a' * 40]},
                  {'title': case.request.game_name + ' – v1.1', 'uploadDate': '2026-01-01',
                   'uris': ['magnet:?xt=urn:btih:' + 'b' * 40]},
              ]}
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', return_value=source), \
         patch('sharewarez.utils.request_notifications.notify_request_updated'):
        result = execute_lookup(context(), {'request_id': case.request.id, 'user_id': case.user.id})
    assert result['status'] == ('fulfilled' if enabled else 'ambiguous')
    if enabled:
        assert case.request.fulfilled_game.torrent_sources[0].info_hash_v1 == 'b' * 40
        assert 'most recent upload' in case.request.torrent_lookup_message


def test_fulfilment_creates_one_pathless_game_and_satisfies_request(torrent_request):
    case = torrent_request
    result, notify = run_lookup(case)
    assert result['status'] == 'fulfilled'
    game = case.session.query(Game).filter_by(uuid=result['game_uuid']).one()
    assert game.full_disk_path is None
    assert game.library_uuid == case.library.uuid
    assert len(game.torrent_sources) == 1
    assert case.request.status == 'fulfilled'
    assert case.request.handled_by_user_id is None
    assert case.request.requesters[0].satisfied_by_game_uuid == game.uuid
    notify.assert_called_once()
    again, second_notification = run_lookup(case)
    assert again['status'] == 'fulfilled'
    assert case.request.torrent_lookup_status == 'fulfilled'
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 1
    second_notification.assert_not_called()


@pytest.mark.parametrize('change', ['revoke', 'withdraw', 'resolve'])
def test_rechecks_permission_and_request_after_remote_fetch(torrent_request, change):
    case = torrent_request
    def fetch(url):
        if change == 'revoke':
            case.user.can_auto_fulfill_torrent_requests = False
        elif change == 'withdraw':
            case.request.requesters[0].withdrawn_at = datetime.now(timezone.utc)
        else:
            case.request.status = 'not_planned'
        case.session.commit()
        return {}
    result, notify = run_lookup(case, fetch=fetch)
    assert result['status'] == 'skipped'
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 0
    notify.assert_not_called()


@pytest.mark.parametrize('status', ['not_found', 'ambiguous'])
def test_uncertain_match_keeps_request_pending(torrent_request, status):
    case = torrent_request
    result, notify = run_lookup(case, match={'status': status, 'entry': None})
    assert result['status'] == status
    assert case.request.status == 'pending'
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 0
    notify.assert_not_called()


def test_source_failure_records_reason_and_allows_worker_retry(torrent_request):
    case = torrent_request
    def fail(url):
        raise ValueError('Unavailable')
    with pytest.raises(RuntimeError, match='catalogue unavailable'):
        run_lookup(case, fetch=fail, match={'status': 'not_found', 'entry': None})
    assert case.request.torrent_lookup_status == 'source_error'
    assert case.request.status == 'pending'


def test_partial_catalogue_failure_never_fulfils_from_incomplete_matches(torrent_request):
    case = torrent_request
    case.settings.settings = {**case.settings.settings,
        'torrentCatalogueUrls': 'https://example.com/catalogue.json\nhttps://example.com/other.json'}
    case.session.commit()
    def fetch(url):
        if url.endswith('/other.json'):
            raise OSError('Temporary outage')
        return {}
    with pytest.raises(RuntimeError, match='catalogue unavailable'):
        run_lookup(case, fetch=fetch)
    assert case.request.status == 'pending'
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 0


def test_transient_torrent_fetch_failure_can_be_retried(torrent_request):
    case = torrent_request
    entry = {'title': case.request.game_name, 'uris': ['https://example.com/release.torrent'],
             'source_name': 'Public source', 'source_url': 'https://example.com/catalogue.json'}
    with patch('sharewarez.utils.torrent_catalogues.fetch_bytes', side_effect=OSError('Temporary outage')):
        with pytest.raises(RuntimeError, match='torrent file unavailable'):
            run_lookup(case, match={'status': 'matched', 'entry': entry})
    assert case.request.status == 'pending' and case.request.torrent_lookup_status == 'source_error'


@pytest.mark.parametrize('change', ['before', 'during'])
def test_queued_enrichment_cannot_apply_metadata_to_a_changed_identity(torrent_request, change):
    from sharewarez.utils.background_jobs import torrent_request_enrich
    case = torrent_request
    result, _ = run_lookup(case)
    game = case.request.fulfilled_game
    identity = game.external_identities[0]
    expected_id = identity.external_id
    if change == 'before':
        identity.external_id = uuid4().hex
        case.session.commit()
    def fetch(provider, external_id):
        identity.external_id = uuid4().hex
        case.session.commit()
        return {'game_name': 'Must not apply'}
    with patch('sharewarez.utils.game_requests.fetch_metadata_game', side_effect=fetch):
        outcome = torrent_request_enrich(context(), {'game_uuid': game.uuid,
            'expected_provider': 'rawg', 'expected_external_id': expected_id})
    assert outcome['skipped'] is True
    assert game.name == case.request.game_name


def test_unrelated_settings_change_does_not_discard_a_valid_lookup(torrent_request):
    case = torrent_request
    def fetch(url):
        case.settings.settings = {**case.settings.settings, 'showHelpButton': False}
        case.session.commit()
        return {}
    result, _ = run_lookup(case, fetch=fetch)
    assert result['status'] == 'fulfilled'


def test_legacy_igdb_request_retains_its_verified_identity(torrent_request):
    case = torrent_request
    case.request.metadata_provider = None
    case.request.provider_game_id = None
    case.request.igdb_id = 1_500_000_000 + uuid4().int % 400_000_000
    case.session.commit()
    result, _ = run_lookup(case)
    assert result['status'] == 'fulfilled'
    game = case.request.fulfilled_game
    assert game.igdb_id == case.request.igdb_id
    assert game.external_identities[0].provider == 'igdb'


def test_unexpected_worker_failure_does_not_leave_request_looking_up(torrent_request):
    from sharewarez.utils.background_jobs import execute
    case = torrent_request
    job = queue_lookup(case.request, case.user)
    job.status = 'running'
    job.locked_by = 'audit-worker'
    job.attempts = 1
    case.session.commit()
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', side_effect=RuntimeError('Unexpected transport failure')):
        execute(job, 'audit-worker')
    assert case.request.torrent_lookup_status == 'source_error'
    assert job.status == 'queued'  # Bounded durable retry is retained.


def test_request_queue_can_fulfil_while_a_scan_is_running(torrent_request, app):
    from threading import Event
    from sharewarez.job_worker import maintain_request_lookups
    case = torrent_request
    scan = BackgroundJob(task_name='library.scan', status='running', locked_by='busy-scan-worker')
    case.session.add(scan)
    job = queue_lookup(case.request, case.user)
    job.created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    case.session.commit()
    assert job.queue == 'requests'
    stopping = Event()
    def fetch(url):
        stopping.set()
        return {'name': 'Test', 'source_url': url, 'downloads': [
            {'title': case.request.game_name, 'uris': ['magnet:?xt=urn:btih:' + 'c' * 40]}]}
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', side_effect=fetch), \
         patch('sharewarez.utils.request_notifications.notify_request_updated'):
        maintain_request_lookups(app, stopping)
    case.session.expire_all()
    assert job.status == 'completed'
    assert case.request.status == 'fulfilled'
    assert scan.status == 'running'


def test_attachment_failure_rolls_back_new_game(torrent_request):
    case = torrent_request
    with patch('sharewarez.utils.torrent_requests.attach_prepared', side_effect=RuntimeError('disk error')):
        with pytest.raises(RuntimeError, match='disk error'):
            run_lookup(case)
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 0
    assert case.request.status == 'pending'


def test_existing_identity_is_reused_without_duplicate_game(torrent_request):
    from sharewarez.models import GameExternalIdentity
    case = torrent_request
    existing = Game(name=case.request.game_name, library_uuid=case.library.uuid)
    existing.external_identities.append(GameExternalIdentity(provider='rawg',
        external_id=case.request.provider_game_id, canonical=True))
    case.session.add(existing)
    case.session.commit()
    result, notify = run_lookup(case)
    assert result['status'] == 'fulfilled'
    assert result['game_uuid'] == existing.uuid
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 1
    assert len(existing.torrent_sources) == 1


def test_update_requests_never_trigger_automation(torrent_request):
    case = torrent_request
    case.request.request_type = 'update'
    assert not eligible(case.request, case.user, case.settings.settings)
    assert queue_lookup(case.request, case.user) is None


def test_terminal_lookup_requires_explicit_admin_retry(torrent_request):
    case = torrent_request
    case.request.torrent_lookup_status = 'not_found'
    assert queue_lookup(case.request, case.user) is None
    job = queue_lookup(case.request, case.user, retry=True)
    assert job is not None
    assert case.request.torrent_lookup_status == 'queued'


@pytest.mark.parametrize('job_status', ['queued', 'running'])
def test_active_job_blocks_explicit_retry(torrent_request, job_status):
    case = torrent_request
    job = queue_lookup(case.request, case.user)
    job.status = job_status
    case.request.torrent_lookup_status = 'looking_up'
    case.session.flush()
    assert queue_lookup(case.request, case.user, retry=True) is None


@pytest.mark.parametrize('job_status', ['failed', 'cancelled'])
def test_stale_lookup_with_terminal_job_allows_explicit_retry(torrent_request, job_status):
    case = torrent_request
    job = queue_lookup(case.request, case.user)
    job.status = job_status
    case.request.torrent_lookup_status = 'looking_up'
    case.session.flush()
    retry = queue_lookup(case.request, case.user, retry=True)
    assert retry is not None
    assert retry.id != job.id
    assert case.request.torrent_lookup_status == 'queued'


def test_any_edition_satisfies_only_same_provider_parent(torrent_request):
    case = torrent_request
    case.request.provider_parent_id = 'family-' + uuid4().hex
    links = {}
    for variant, provider, accepts, withdrawn in [
        ('accepts', 'rawg', True, False), ('exact', 'rawg', False, False),
        ('withdrawn', 'rawg', True, True), ('other_provider', 'igdb', True, False),
    ]:
        sibling = GameRequest(game_name='Other edition ' + uuid4().hex, status='pending',
            request_type='new_game', metadata_provider=provider,
            provider_game_id=uuid4().hex, provider_parent_id=case.request.provider_parent_id)
        link = GameRequestUser(user=case.user, accept_any_edition=accepts,
            withdrawn_at=datetime.now(timezone.utc) if withdrawn else None)
        sibling.requesters.append(link)
        case.session.add(sibling)
        links[variant] = link
    case.session.commit()
    result, notify = run_lookup(case)
    assert result['status'] == 'fulfilled'
    assert links['accepts'].satisfied_by_game_uuid == result['game_uuid']
    for variant in ('exact', 'withdrawn', 'other_provider'):
        assert links[variant].satisfied_at is None
    assert notify.call_args.kwargs['commit'] is False
    assert links['accepts'] in notify.call_args.args[1]


def test_actual_notification_commits_with_fulfilment(torrent_request):
    from sharewarez.models import Notification, NotificationEvent
    from sharewarez.utils.request_notifications import notify_request_updated
    case = torrent_request
    # run_lookup patches only the top-level callable: wrapping it exercises the real
    # event publisher while checking that it receives the uncommitted game changes.
    entry = {'title': case.request.game_name, 'uris': ['magnet:?xt=urn:btih:' + 'c' * 40],
             'source_name': 'Public catalogue', 'source_url': 'https://example.com/catalogue.json'}
    observed = []
    def notify(record, links, *, commit):
        assert commit is False
        assert record.fulfilled_game is not None
        case.session.flush()
        assert case.session.query(Game).filter_by(uuid=record.fulfilled_game_uuid).one()
        observed.append(record.fulfilled_game_uuid)
        return notify_request_updated(record, links, commit=False)
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', return_value={}), \
         patch('sharewarez.utils.torrent_catalogues.match_catalogues', return_value={'status': 'matched', 'entry': entry}), \
         patch('sharewarez.utils.request_notifications.notify_request_updated', side_effect=notify):
        result = execute_lookup(context(), {'request_id': case.request.id, 'user_id': case.user.id})
    event = case.session.query(NotificationEvent).filter_by(
        dedupe_key=f'request-update:{case.request.id}:fulfilled').one()
    assert observed == [result['game_uuid']]
    assert event.resource_id == str(case.request.id)
    assert case.session.query(Notification).filter_by(event_id=event.id, user_id=case.user.id).count() == 1
    case.session.expire_all()
    assert case.request.status == 'fulfilled'
    assert case.request.torrent_lookup_status == 'fulfilled'


def test_notification_failure_rolls_back_game_sources_and_fulfilment(torrent_request):
    from sharewarez.models import GameTorrentSource, NotificationEvent
    case = torrent_request
    entry = {'title': case.request.game_name, 'uris': ['magnet:?xt=urn:btih:' + 'd' * 40],
             'source_name': 'Public catalogue', 'source_url': 'https://example.com/catalogue.json'}
    def notify(record, links, *, commit):
        case.session.add(NotificationEvent(event_type='request_updated', title='Will roll back',
            message='test', dedupe_key=f'rollback-{record.id}'))
        case.session.flush()
        raise RuntimeError('notification staging failed')
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', return_value={}), \
         patch('sharewarez.utils.torrent_catalogues.match_catalogues', return_value={'status': 'matched', 'entry': entry}), \
         patch('sharewarez.utils.request_notifications.notify_request_updated', side_effect=notify):
        with pytest.raises(RuntimeError, match='notification staging failed'):
            execute_lookup(context(), {'request_id': case.request.id, 'user_id': case.user.id})
    assert case.session.query(Game).filter_by(name=case.request.game_name).count() == 0
    assert case.session.query(NotificationEvent).filter_by(dedupe_key=f'rollback-{case.request.id}').count() == 0
    assert case.request.fulfilled_game_uuid is None
    assert case.request.status == 'pending'


def test_torrent_request_migration_upgrade_idempotence_and_downgrade(db_session):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from sharewarez import db
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261117_37_torrent_requests.py'
    spec = importlib.util.spec_from_file_location('torrent_request_migration_test', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = 'torrent_migration_' + uuid4().hex
    with db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            connection.execute(text('CREATE TABLE users (id integer PRIMARY KEY)'))
            connection.execute(text('INSERT INTO users VALUES (1)'))
            connection.execute(text('CREATE TABLE game_requests (id integer PRIMARY KEY)'))
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
                migration.upgrade()
                assert connection.execute(text('SELECT can_auto_fulfill_torrent_requests FROM users')).scalar() is False
                assert {'torrent_lookup_status', 'torrent_lookup_message'} <= {
                    item['name'] for item in inspect(connection).get_columns('game_requests')}
                migration.downgrade()
                assert {item['name'] for item in inspect(connection).get_columns('users')} == {'id'}
                assert {item['name'] for item in inspect(connection).get_columns('game_requests')} == {'id'}
        finally:
            transaction.rollback()
