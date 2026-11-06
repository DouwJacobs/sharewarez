from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from sharewarez.models import DownloadRequest, DownloadTransfer, Game, GlobalSettings, Library, User
from sharewarez.platform import LibraryPlatform


@pytest.fixture
def state_link(app, client, db_session, tmp_path):
    app.config.update(BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path), DATA_FOLDER_WAREZ=str(tmp_path), DOWNLOAD_CACHE_DIR=str(tmp_path / 'cache'))
    root = tmp_path / 'Game'
    root.mkdir()
    (root / 'one.bin').write_bytes(b'one')
    (root / 'two.bin').write_bytes(b'two')
    user = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='user', password_hash='unused', state=True)
    library = Library(name=uuid4().hex, platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library])
    db_session.flush()
    game = Game(name='State fixture', full_disk_path=str(root), library_uuid=library.uuid)
    db_session.add(game)
    db_session.flush()
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.settings = {**(settings.settings or {}), 'archiveCacheMode': 'prefer', 'archiveCacheFallbackEnabled': True}
    link = DownloadRequest(user_id=user.id, game_uuid=game.uuid, status='failed', file_location=str(root), zip_file_path=str(root), delivery_kind='live_archive', expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db_session.add(link)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    return client, link, settings, root


@pytest.mark.parametrize('status', ['expired', 'cancelled'])
def test_terminal_link_cannot_be_revived_by_fallback(state_link, db_session, status):
    client, link, settings, root = state_link
    link.status = status
    db_session.commit()
    before = (link.status, link.archive_id, link.delivery_kind, link.expires_at)
    assert client.post(f'/downloads/{link.id}/stream-without-resume').status_code == 302
    db_session.refresh(link)
    assert (link.status, link.archive_id, link.delivery_kind, link.expires_at) == before


def test_active_attempt_blocks_retry_even_when_link_is_failed(state_link, db_session):
    client, link, settings, root = state_link
    db_session.add(DownloadTransfer(user_id=link.user_id, download_request_id=link.id, filename='active.zip', status='active'))
    db_session.commit()
    before = (link.status, link.archive_id, link.delivery_kind, link.expires_at)
    client.post(f'/downloads/{link.id}/retry')
    db_session.refresh(link)
    assert (link.status, link.archive_id, link.delivery_kind, link.expires_at) == before


def test_retry_with_cache_off_makes_directory_available(state_link, db_session):
    client, link, settings, root = state_link
    settings.settings = {**settings.settings, 'archiveCacheMode': 'off'}
    db_session.commit()
    assert client.post(f'/downloads/{link.id}/retry').status_code == 302
    db_session.refresh(link)
    assert link.status == 'available' and link.delivery_kind == 'live_archive' and link.archive_id is None

@pytest.mark.parametrize('mode,healthy,fallback,status,kind', [
    ('off', True, True, 'available', 'live_archive'),
    ('prefer', True, True, 'processing', 'cached_archive'),
    ('prefer', False, True, 'available', 'live_archive'),
    ('prefer', False, False, 'failed', 'cached_archive'),
    ('require', False, True, 'failed', 'cached_archive'),
    ('require', True, False, 'processing', 'cached_archive'),
])
def test_retry_policy_matrix(state_link, db_session, monkeypatch, mode, healthy, fallback, status, kind):
    client, link, settings, root = state_link
    settings.settings = {**settings.settings, 'archiveCacheMode': mode, 'archiveCacheFallbackEnabled': fallback}
    db_session.commit()
    monkeypatch.setattr('sharewarez.utils.download_cache.cache_health', lambda: {'healthy': healthy, 'message': 'Cache unavailable'})
    client.post(f'/downloads/{link.id}/retry')
    db_session.refresh(link)
    assert (link.status, link.delivery_kind) == (status, kind)
    assert bool(link.archive_id) == (status == 'processing')


@pytest.mark.parametrize('case', ['expired_time', 'cancelled', 'active', 'direct_shortcut', 'missing_source', 'failed_cache'])
def test_initial_html_polling_and_snapshot_share_state_and_actions(state_link, db_session, app, case):
    from bs4 import BeautifulSoup
    from sharewarez.live_snapshots import snapshot_data
    client, link, settings, root = state_link
    if case == 'expired_time':
        link.status = 'available'
        link.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif case == 'cancelled':
        link.status = 'cancelled'
    elif case == 'active':
        db_session.add(DownloadTransfer(user_id=link.user_id, download_request_id=link.id, filename='active.bin', status='active', delivery_kind='direct'))
    elif case == 'direct_shortcut':
        link.status = 'available'
        link.delivery_kind = 'direct'
        link.zip_file_path = str(root / 'one.bin')
    elif case == 'missing_source':
        link.status = 'available'
        link.file_location = str(root / 'missing')
    db_session.commit()
    page = BeautifulSoup(client.get('/downloads').data, 'html.parser')
    row = page.select_one(f'[data-download-id="{link.id}"]')
    visible = {node['data-action'] for node in row.select('[data-action]') if not node.has_attr('hidden')}
    polled = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    with app.app_context():
        live = snapshot_data('downloads', [link.id], link.user_id)['downloads'][0]
    assert row['data-download-status'] == polled['status'] == live['status']
    assert visible == set(polled['allowed_actions']) == set(live['allowed_actions'])
    assert row.select_one('.download-delivery-badge').get_text(strip=True) == polled['delivery_label'] == live['delivery_label']
    assert b'On this page' in client.get('/downloads').data
    if case == 'direct_shortcut':
        assert polled['delivery_label'] == 'Resumable'
    if case == 'active':
        assert polled['allowed_actions'] == []
    if case == 'missing_source':
        assert polled['allowed_actions'] == ['delete']
    if case in {'expired_time', 'cancelled'}:
        assert polled['allowed_actions'] == ['retry']


def test_renew_validates_source_before_changing_expiry_or_status(state_link, db_session):
    client, link, settings, root = state_link
    link.status = 'expired'
    link.file_location = str(root / 'missing')
    link.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()
    before = (link.status, link.expires_at, link.zip_file_path, link.archive_id)
    client.post(f'/downloads/{link.id}/retry')
    db_session.refresh(link)
    assert (link.status, link.expires_at, link.zip_file_path, link.archive_id) == before


def test_shared_archive_keeps_owner_actions_and_latest_attempt_isolated(state_link, app, db_session):
    from sharewarez.utils.download_state import prepare_download
    from sharewarez.live_snapshots import snapshot_data
    client, link, settings, root = state_link
    prepare_download(link)
    second = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='user', password_hash='unused', state=True)
    db_session.add(second)
    db_session.flush()
    other = DownloadRequest(user_id=second.id, game_uuid=link.game_uuid, status='failed', file_location=str(root), zip_file_path=str(root))
    db_session.add(other)
    prepare_download(other)
    assert other.archive_id == link.archive_id
    db_session.add_all([
        DownloadTransfer(user_id=second.id, download_request_id=other.id, status='active', filename='other.zip'),
        DownloadTransfer(user_id=link.user_id, download_request_id=link.id, status='interrupted', filename='mine.zip', end_reason='peer_disconnect', bytes_sent=2, reserved_bytes=2),
    ])
    db_session.commit()
    data = client.get(f'/api/downloads/status?ids={link.id},{other.id}').get_json()
    assert [row['id'] for row in data['downloads']] == [link.id]
    mine = data['downloads'][0]
    assert mine['active_transfer'] is None and mine['latest_attempt']['end_reason'] == 'peer_disconnect'
    assert mine['status'] == 'processing'
    for action in ('retry', 'cancel', 'stream-without-resume'):
        assert client.post(f'/downloads/{other.id}/{action}').status_code == 404
    with app.app_context():
        live = snapshot_data('downloads', [link.id, other.id], link.user_id)
    assert live['transfers'] == [] and [row['id'] for row in live['downloads']] == [link.id]


def test_new_require_failure_is_recoverable_without_new_link_on_retry(state_link, db_session, monkeypatch):
    client, old, settings, root = state_link
    game_uuid = old.game_uuid
    db_session.delete(old)
    settings.settings = {**settings.settings, 'archiveCacheMode': 'require'}
    db_session.commit()
    monkeypatch.setattr('sharewarez.utils.download_cache.cache_health', lambda: {'healthy': False, 'message': 'Cache unavailable'})
    assert client.post(f'/download_game/{game_uuid}').location.endswith('/downloads')
    link = db_session.query(DownloadRequest).filter_by(game_uuid=game_uuid).one()
    assert link.status == 'failed'
    identity = link.id
    monkeypatch.setattr('sharewarez.utils.download_cache.cache_health', lambda: {'healthy': True})
    client.post(f'/downloads/{identity}/retry')
    db_session.refresh(link)
    assert link.id == identity and link.status == 'processing' and link.archive_id
    assert db_session.query(DownloadRequest).filter_by(game_uuid=game_uuid).count() == 1

@pytest.mark.parametrize('mode,healthy,status', [('off', True, 'available'), ('require', False, 'failed')])
def test_admin_bulk_retry_uses_same_policy_and_preserves_active_link(state_link, db_session, monkeypatch, mode, healthy, status):
    client, link, settings, root = state_link
    user = db_session.get(User, link.user_id)
    user.role = 'admin'
    settings.settings = {**settings.settings, 'archiveCacheMode': mode}
    db_session.commit()
    monkeypatch.setattr('sharewarez.utils.download_cache.cache_health', lambda: {'healthy': healthy, 'message': 'Cache unavailable'})
    response = client.post('/api/downloads/bulk', json={'action': 'retry', 'ids': [link.id]})
    assert response.get_json()['changed'] == 1
    db_session.refresh(link)
    assert link.status == status
    link.status = 'failed'
    db_session.add(DownloadTransfer(user_id=link.user_id, download_request_id=link.id, filename='active.zip', status='active'))
    db_session.commit()
    before = (link.status, link.expires_at, link.archive_id)
    assert client.post('/api/downloads/bulk', json={'action': 'retry', 'ids': [link.id]}).get_json()['changed'] == 0
    db_session.refresh(link)
    assert (link.status, link.expires_at, link.archive_id) == before


def test_reopening_active_or_expired_link_does_not_start_or_renew_it(state_link, db_session):
    client, link, settings, root = state_link
    link.status = 'available'
    transfer = DownloadTransfer(user_id=link.user_id, download_request_id=link.id, status='active', filename='active.zip')
    db_session.add(transfer)
    db_session.commit()
    expiry = link.expires_at
    assert client.post(f'/download_game/{link.game_uuid}').location.endswith('/downloads')
    db_session.refresh(link)
    assert link.expires_at == expiry and link.status == 'available'
    transfer.status = 'interrupted'
    link.status = 'expired'
    db_session.commit()
    assert client.post(f'/download_game/{link.game_uuid}').location.endswith('/downloads')
    db_session.refresh(link)
    assert link.status == 'expired' and link.expires_at == expiry


def test_valid_cached_link_can_reopen_with_original_source_offline(state_link, db_session, tmp_path):
    from types import SimpleNamespace
    from sharewarez.utils.download_state import prepare_download
    from sharewarez.utils.download_cache import build_archive
    client, link, settings, root = state_link
    settings.settings = {**settings.settings, 'archiveCacheMinFreeGb': 0}
    db_session.commit()
    prepare_download(link)
    db_session.commit()
    archive = link.archive
    build_archive(SimpleNamespace(job_id=archive.build_job_id, heartbeat=lambda *args: None, check_cancelled=lambda: None), archive.id)
    db_session.refresh(link)
    root.rename(tmp_path / 'offline')
    response = client.post(f'/download_game/{link.game_uuid}')
    assert response.location.endswith(f'/download_zip/{link.id}')
    assert db_session.query(DownloadRequest).filter_by(user_id=link.user_id).count() == 1


def test_legacy_file_path_only_link_can_renew(state_link, db_session):
    client, link, settings, root = state_link
    link.file_location = None
    link.zip_file_path = str(root / 'one.bin')
    link.status = 'expired'
    db_session.commit()
    client.post(f'/downloads/{link.id}/retry')
    db_session.refresh(link)
    assert link.status == 'available' and link.delivery_kind == 'direct'
    assert link.file_location == str(root / 'one.bin')


def test_post_observes_transfer_committed_while_waiting_for_owner_lock(state_link, app, db_session, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import select
    from sharewarez import db
    from sharewarez.utils import download_state as states
    client, link, settings, root = state_link
    identity, uid = link.id, link.user_id
    locked, posting, release = Event(), Event(), Event()
    original = states.lock_download
    def lock(*args, **kwargs):
        posting.set()
        return original(*args, **kwargs)
    monkeypatch.setattr(states, 'lock_download', lock)
    def writer():
        with app.app_context():
            db.session.execute(select(User).where(User.id == uid).with_for_update()).scalar_one()
            db.session.add(DownloadTransfer(user_id=uid, download_request_id=identity, status='active', filename='racing.zip'))
            db.session.flush()
            locked.set()
            assert release.wait(5)
            db.session.commit()
    def post():
        with app.app_context(), app.test_client() as browser:
            with browser.session_transaction() as session:
                session['_user_id'] = str(uid)
                session['_fresh'] = True
            return browser.post(f'/downloads/{identity}/retry').status_code
    before = (link.status, link.archive_id, link.expires_at)
    with ThreadPoolExecutor(max_workers=2) as executor:
        inserting = executor.submit(writer)
        assert locked.wait(5)
        submitting = executor.submit(post)
        try:
            assert posting.wait(5)
        finally:
            release.set()
        inserting.result(timeout=5)
        assert submitting.result(timeout=5) == 302
    db_session.refresh(link)
    assert (link.status, link.archive_id, link.expires_at) == before


def test_admission_revalidates_representation_after_link_action(state_link, db_session):
    from sharewarez.utils.download_limits import DownloadAdmissionRejected, reserve_transfer
    client, link, settings, root = state_link
    link.status, link.delivery_kind = 'available', 'direct'
    old = str(root / 'one.bin')
    link.zip_file_path = str(root / 'two.bin')
    db_session.commit()
    with pytest.raises(DownloadAdmissionRejected, match='representation changed'):
        reserve_transfer(link.user_id, 'one.bin', 3, download_request_id=link.id, source_path=old)
    db_session.rollback()
    assert db_session.query(DownloadTransfer).filter_by(download_request_id=link.id).count() == 0

def test_missing_cached_file_is_read_only_failure_then_retry_requeues(state_link, app, db_session):
    from types import SimpleNamespace
    from sharewarez.utils.download_state import prepare_download
    from sharewarez.utils.download_cache import build_archive, resolved_archive_path
    client, link, settings, root = state_link
    settings.settings = {**settings.settings, 'archiveCacheMinFreeGb': 0}
    db_session.commit()
    prepare_download(link)
    db_session.commit()
    archive = link.archive
    build_archive(SimpleNamespace(job_id=archive.build_job_id, heartbeat=lambda *args: None, check_cancelled=lambda: None), archive.id)
    db_session.refresh(link)
    db_session.refresh(archive)
    identity = archive.id
    resolved_archive_path(archive).unlink()
    data = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    assert data['status'] == 'failed' and set(data['allowed_actions']) == {'retry', 'fallback', 'delete'}
    db_session.refresh(link)
    db_session.refresh(archive)
    assert link.status == 'available' and archive.state == 'ready'
    client.post(f'/downloads/{link.id}/retry')
    db_session.refresh(link)
    db_session.refresh(archive)
    assert link.status == 'processing' and link.archive_id == identity and archive.state == 'queued'


def test_legacy_completed_file_and_shared_build_have_accurate_states(state_link, db_session):
    from sharewarez.utils.download_state import prepare_download
    client, link, settings, root = state_link
    link.status, link.delivery_kind = 'completed', 'direct'
    link.file_location = None
    link.zip_file_path = str(root / 'one.bin')
    db_session.commit()
    data = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    assert data['status'] == 'available' and data['delivery_label'] == 'Resumable'
    link.file_location = link.zip_file_path = str(root)
    prepare_download(link)
    link.status = 'available'  # Another owner/admin rebuild can change the shared archive.
    db_session.commit()
    data = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    assert data['status'] == 'processing' and 'download' not in data['allowed_actions']


def test_active_expired_link_still_shows_progress_and_no_mutations(state_link, db_session):
    client, link, settings, root = state_link
    link.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(DownloadTransfer(user_id=link.user_id, download_request_id=link.id, filename='active.zip', status='active'))
    db_session.commit()
    data = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    assert data['display_status'] == 'Downloading' and data['allowed_actions'] == []


def test_unsafe_legacy_path_is_not_offered_or_mutated(state_link, app, db_session, tmp_path):
    client, link, settings, root = state_link
    outside = tmp_path / 'outside.bin'
    outside.write_bytes(b'outside')
    app.config.update(BASE_FOLDER_POSIX=str(root), BASE_FOLDER_WINDOWS=str(root), DATA_FOLDER_WAREZ=str(root))
    link.file_location = link.zip_file_path = str(outside)
    link.status, link.delivery_kind = 'available', 'direct'
    db_session.commit()
    response = client.get(f'/api/downloads/status?ids={link.id}')
    assert str(outside).encode() not in response.data
    assert response.get_json()['downloads'][0]['status'] == 'failed'
    expiry = link.expires_at
    client.post(f'/downloads/{link.id}/retry')
    db_session.refresh(link)
    assert link.expires_at == expiry and link.status == 'available'

def test_member_cancel_preserves_shared_build_then_admin_cancel_has_one_cause(state_link, db_session):
    from sharewarez.utils.download_state import download_state, prepare_download
    client, mine, settings, root = state_link
    prepare_download(mine)
    other_user = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='user', password_hash='unused', state=True)
    db_session.add(other_user)
    db_session.flush()
    other = DownloadRequest(user_id=other_user.id, game_uuid=mine.game_uuid, status='failed', file_location=str(root), zip_file_path=str(root))
    db_session.add(other)
    prepare_download(other)
    db_session.commit()
    archive = mine.archive
    assert mine.archive_id == other.archive_id
    client.post(f'/downloads/{mine.id}/cancel')
    db_session.refresh(mine)
    db_session.refresh(archive)
    assert mine.status == 'cancelled' and archive.state == 'queued' and not archive.build_job.cancel_requested
    assert download_state(mine)['allowed_actions'] == ['retry']
    assert download_state(other)['status'] == 'processing'
    db_session.get(User, mine.user_id).role = 'admin'
    db_session.commit()
    assert client.post(f'/admin/download-cache/entries/{archive.id}/cancel').status_code == 302
    db_session.refresh(archive)
    db_session.refresh(other)
    assert archive.state == 'failed' and download_state(mine)['status'] == 'cancelled'
    state = download_state(other)
    assert state['status'] == 'failed' and 'administrator stopped' in state['message']
    assert str(root) not in state['message']


def test_reopening_legacy_completed_file_only_path_reuses_its_link(state_link, db_session):
    client, link, settings, root = state_link
    game = db_session.query(Game).filter_by(uuid=link.game_uuid).one()
    game.full_disk_path = link.zip_file_path = str(root / 'one.bin')
    link.file_location, link.status = None, 'completed'
    db_session.commit()
    assert client.post(f'/download_game/{link.game_uuid}').location.endswith(f'/download_zip/{link.id}')
    assert db_session.query(DownloadRequest).filter_by(user_id=link.user_id).count() == 1


def test_fallback_rechecks_source_before_mutation(state_link, db_session, monkeypatch):
    from sharewarez.utils import download_state as states
    client, link, settings, root = state_link
    original = states.validated_source
    calls = []
    def validate(value):
        calls.append(True)
        if len(calls) > 1:
            raise ValueError('Source disappeared')
        return original(value)
    monkeypatch.setattr(states, 'validated_source', validate)
    before = (link.status, link.archive_id, link.expires_at)
    assert client.post(f'/downloads/{link.id}/stream-without-resume').status_code == 302
    db_session.refresh(link)
    assert (link.status, link.archive_id, link.expires_at) == before

@pytest.mark.parametrize('fallback', [True, False])
def test_expired_cached_link_requires_renewal_before_any_fallback(state_link, db_session, fallback):
    from sharewarez.utils.download_state import prepare_download
    client, link, settings, root = state_link
    prepare_download(link)
    settings.settings = {**settings.settings, 'archiveCacheFallbackEnabled': fallback}
    link.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    before = (link.status, link.archive_id, link.expires_at)
    data = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    assert data['status'] == 'expired' and data['allowed_actions'] == ['retry'] and data['retry_label'] == 'Renew'
    client.post(f'/downloads/{link.id}/stream-without-resume')
    db_session.refresh(link)
    assert (link.status, link.archive_id, link.expires_at) == before


def test_stale_fallback_form_observes_changed_policy(state_link, db_session):
    client, link, settings, root = state_link
    data = client.get(f'/api/downloads/status?ids={link.id}').get_json()['downloads'][0]
    assert 'fallback' in data['allowed_actions']
    settings.settings = {**settings.settings, 'archiveCacheMode': 'require'}
    db_session.commit()
    before = (link.status, link.delivery_kind, link.archive_id, link.expires_at)
    client.post(f'/downloads/{link.id}/stream-without-resume')
    db_session.refresh(link)
    assert (link.status, link.delivery_kind, link.archive_id, link.expires_at) == before


def test_double_retry_posts_accept_one_transition(state_link, app, db_session, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sharewarez.models import BackgroundJob
    from sharewarez.utils import download_state as states
    client, link, settings, root = state_link
    uid, identity = link.user_id, link.id
    barrier, accepted = Barrier(2), []
    original = states.apply_action
    def action(*args, **kwargs):
        result = original(*args, **kwargs)
        accepted.append(result[0])
        return result
    monkeypatch.setattr(states, 'apply_action', action)
    def post():
        with app.app_context(), app.test_client() as browser:
            with browser.session_transaction() as session:
                session['_user_id'] = str(uid)
                session['_fresh'] = True
            barrier.wait(timeout=5)
            return browser.post(f'/downloads/{identity}/retry').status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: post(), range(2))) == [302, 302]
    assert sorted(accepted) == [False, True]
    db_session.refresh(link)
    archive = link.archive
    jobs = [job for job in db_session.query(BackgroundJob).filter_by(task_name='download.archive.build').all() if job.payload.get('archive_id') == archive.id]
    assert len(jobs) == 1 and link.status == 'processing'