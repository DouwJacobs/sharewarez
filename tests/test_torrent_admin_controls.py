from unittest.mock import patch
from uuid import uuid4

import pytest
from flask import g

from sharewarez.models import GameRequest, GameRequestUser, GlobalSettings, Library, User
from sharewarez.platform import LibraryPlatform
from sharewarez.routes_admin_ext.settings import validate_settings_data


def login(client, user):
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


@pytest.fixture
def accounts(db_session):
    token = uuid4().hex
    users = [User(name=role + token, email=role + token + '@example.test',
                  role=role, state=True, password_hash='unused') for role in ('admin', 'user')]
    db_session.add_all(users)
    db_session.commit()
    return users


@pytest.mark.parametrize('data', [
    {'autoFulfillTorrentRequests': 'yes'},
    {'torrentPreferLatestUpload': 'yes'},
    {'torrentCatalogueUrls': []},
    {'torrentCatalogueUrls': 'file:///tmp/source.json'},
    {'torrentCatalogueUrls': '\n'.join('https://example.test/' + str(n) for n in range(6))},
    {'torrentDestinationLibraryUuid': False},
])
def test_invalid_automation_settings_are_rejected(data):
    assert validate_settings_data(data)


def test_settings_require_catalogue_and_destination(client, db_session, accounts):
    login(client, accounts[0])
    record = db_session.query(GlobalSettings).first()
    if record is None:
        record = GlobalSettings(settings={})
        db_session.add(record)
    record.settings = {**(record.settings or {}), 'autoFulfillTorrentRequests': False,
                       'torrentCatalogueUrls': '', 'torrentDestinationLibraryUuid': ''}
    db_session.commit()
    response = client.post('/admin/settings', json={'section': 'requests', 'settings': {
        'autoFulfillTorrentRequests': True}})
    assert response.status_code == 400
    library = Library(name='Automatic ' + uuid4().hex, platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    response = client.post('/admin/settings', json={'section': 'requests', 'settings': {
        'autoFulfillTorrentRequests': True, 'torrentDestinationLibraryUuid': library.uuid,
        'torrentCatalogueUrls': 'https://example.test/catalogue.json'}})
    assert response.status_code == 200


def test_latest_upload_setting_defaults_off_and_saves_in_requests_section(client, db_session, accounts):
    from sharewarez.settings_defaults import default_settings
    assert default_settings()['torrentPreferLatestUpload'] is False
    login(client, accounts[0])
    for enabled in (True, False):
        response = client.post('/admin/settings', json={'section': 'requests', 'settings': {
            'torrentPreferLatestUpload': enabled}})
        assert response.status_code == 200
        assert db_session.query(GlobalSettings).first().settings['torrentPreferLatestUpload'] is enabled


def test_permission_is_admin_owned_and_strictly_boolean(client, db_session, accounts):
    admin, user = accounts
    login(client, user)
    assert client.put(f'/admin/api/user/{user.id}', json={
        'can_auto_fulfill_torrent_requests': True}).status_code == 302
    login(client, admin)
    assert client.put(f'/admin/api/user/{user.id}', json={
        'can_auto_fulfill_torrent_requests': 'true'}).status_code == 400
    assert client.put(f'/admin/api/user/{user.id}', json={
        'can_auto_fulfill_torrent_requests': True}).status_code == 200
    assert client.get(f'/admin/api/user/{user.id}').json['can_auto_fulfill_torrent_requests'] is True
    assert client.put(f'/admin/api/user/{user.id}', json={
        'can_auto_fulfill_torrent_requests': False}).status_code == 200


def test_source_test_reports_failure_without_fetching_for_members(client, accounts):
    login(client, accounts[1])
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue') as fetch:
        assert client.post('/admin/torrent-catalogues/test', json={
            'urls': 'https://example.test/catalogue.json'}).status_code == 302
        fetch.assert_not_called()
    login(client, accounts[0])
    with patch('sharewarez.utils.torrent_catalogues.fetch_catalogue', side_effect=ValueError('Source unavailable')):
        response = client.post('/admin/torrent-catalogues/test', json={
            'urls': 'https://example.test/catalogue.json'})
    assert response.status_code == 200
    assert response.json['results'][0]['ok'] is False
    assert 'Source unavailable' in response.json['results'][0]['message']


def test_full_user_form_with_empty_about_can_save_permission(client, db_session, accounts):
    admin, user = accounts
    # Legacy accounts may contain an empty string under the unique about column.
    existing = db_session.query(User).filter_by(about='').first()
    if existing is None:
        admin.about = ''
        db_session.commit()
    login(client, admin)
    original_email = user.email
    response = client.put(f'/admin/api/user/{user.id}', json={
        'email': user.email, 'role': user.role, 'state': True,
        'is_email_verified': False, 'can_auto_fulfill_torrent_requests': True,
        'password': '', 'about': '', 'monthly_download_quota_gb': None,
    })
    assert response.status_code == 200, response.json
    db_session.expire_all()
    assert user.email == original_email
    assert user.about is None
    assert user.can_auto_fulfill_torrent_requests is True


def test_retry_requires_pending_request_and_authorized_requester(client, db_session, accounts):
    admin, user = accounts
    game_request = GameRequest(game_name='Retry fixture ' + uuid4().hex, request_type='new_game', status='pending')
    game_request.requesters.append(GameRequestUser(user=user))
    db_session.add(game_request)
    db_session.commit()
    login(client, admin)
    endpoint = f'/admin/game-requests/{game_request.id}/retry-torrent'
    with patch('sharewarez.utils.torrent_requests.queue_lookup') as queue:
        assert client.post(endpoint).status_code == 302
        queue.assert_not_called()
        user.can_auto_fulfill_torrent_requests = True
        db_session.commit()
        assert client.post(endpoint).status_code == 302
        queue.assert_called_once()
        assert queue.call_args.kwargs == {'retry': True}
        queue.reset_mock()
        game_request.status = 'planned'
        db_session.commit()
        assert client.post(endpoint).status_code == 302
        queue.assert_not_called()


def test_source_selection_uses_stored_candidates_and_rejects_stale_choices(client, db_session, accounts):
    from sharewarez.models import BackgroundJob
    admin, user = accounts
    record = GameRequest(game_name='Source choice ' + uuid4().hex, request_type='new_game',
                         status='pending', torrent_lookup_status='ambiguous')
    record.requesters.append(GameRequestUser(user=user))
    db_session.add(record)
    db_session.flush()
    candidate = {'title': 'Source choice', 'uris': ['magnet:?xt=urn:btih:' + 'f' * 40],
                 'source_name': 'Public source', 'source_url': 'https://example.test/catalogue.json'}
    job = BackgroundJob(task_name='requests.torrent_lookup', status='completed',
                        payload={'request_id': record.id}, result={'candidates': [candidate]})
    db_session.add(job)
    db_session.commit()
    endpoint = f'/admin/game-requests/{record.id}/select-torrent'
    login(client, user)
    with patch('sharewarez.utils.torrent_requests.queue_lookup') as queue:
        assert client.post(endpoint, data={'candidate_job': job.id, 'candidate_index': '0'}).status_code == 302
        queue.assert_not_called()
        login(client, admin)
        assert client.post(endpoint, data={'candidate_job': 'stale', 'candidate_index': '0'}).status_code == 302
        queue.assert_not_called()
        assert client.post(endpoint, data={'candidate_job': job.id, 'candidate_index': '99'}).status_code == 302
        queue.assert_not_called()
        assert client.post(endpoint, data={'candidate_job': job.id, 'candidate_index': '0'}).status_code == 302
        assert queue.call_args.kwargs['selected_entry'] == candidate
