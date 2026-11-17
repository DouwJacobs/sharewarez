"""Behavioural coverage for private manual catalogue snapshots."""
import hashlib
from io import BytesIO
import json
from uuid import uuid4

from flask import g
import pytest
from sqlalchemy import delete

from sharewarez.models import GlobalSettings, Library, UploadedTorrentCatalogue, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.torrent_catalogue_uploads import uploaded_metadata

ENDPOINT = '/admin/torrent-catalogues/upload'


def content(title='Uploaded game'):
    return json.dumps({'name': 'Browser catalogue', 'downloads': [{
        'title': title, 'uris': ['magnet:?xt=urn:btih:' + 'a' * 40],
        'uploadDate': '2026-11-17T10:00:00Z', 'fileSize': '4 GB'}]}).encode()


def login(client, user):
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


@pytest.fixture
def upload_case(client, db_session):
    db_session.execute(delete(UploadedTorrentCatalogue))
    token = uuid4().hex
    admin = User(name='upload_admin_' + token[:8], email=token + '@admin.test', role='admin', password_hash='unused')
    member = User(name='upload_user_' + token[:8], email=token + '@user.test', role='user', password_hash='unused')
    library = Library(name='Upload library ' + token, platform=LibraryPlatform.PCWIN)
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db_session.add(settings)
    previous = dict(settings.settings or {})
    settings.settings = {**previous, 'autoFulfillTorrentRequests': False,
                         'torrentCatalogueUrls': '', 'torrentDestinationLibraryUuid': library.uuid}
    db_session.add_all([admin, member, library])
    db_session.commit()
    login(client, admin)
    yield admin, member, settings, library
    db_session.rollback()
    db_session.execute(delete(UploadedTorrentCatalogue))
    settings.settings = previous
    db_session.commit()


def upload(client, payload=None, revision='', filename='fitgirl.json'):
    return client.post(ENDPOINT, data={'file': (BytesIO(payload if payload is not None else content()), filename),
                                       'revision': revision})


def test_upload_replace_and_remove_preserve_drafts_and_require_current_revision(client, db_session, upload_case):
    response = upload(client)
    assert response.status_code == 200
    metadata = response.json['catalogue']
    assert metadata['entry_count'] == 1 and metadata['filename'] == 'fitgirl.json'
    record = db_session.get(UploadedTorrentCatalogue, 1)
    assert record.content == content() and record.sha256 == hashlib.sha256(content()).hexdigest()
    assert 'content' not in metadata
    assert upload_case[2].settings['torrentCatalogueUrls'] == ''
    assert upload(client, content('New game')).status_code == 409
    response = upload(client, content('New game'), metadata['sha256'])
    assert response.status_code == 200
    newer = response.json['catalogue']
    assert newer['sha256'] != metadata['sha256']
    assert client.delete(ENDPOINT, json={'revision': metadata['sha256']}).status_code == 409
    assert client.delete(ENDPOINT, json={'revision': newer['sha256']}).status_code == 200
    assert uploaded_metadata() is None


@pytest.mark.parametrize('payload,filename', [(b'<html>Cloudflare challenge</html>', 'fitgirl.json'),
    (b'{"name":"Empty","downloads":[]}', 'empty.json'), (content(), 'file.txt')])
def test_bad_uploads_leave_the_previous_catalogue_usable(client, db_session, upload_case, payload, filename):
    original = upload(client).json['catalogue']
    response = upload(client, payload, original['sha256'], filename)
    assert response.status_code == 400
    assert uploaded_metadata()['sha256'] == original['sha256']
    assert db_session.get(UploadedTorrentCatalogue, 1).content == content()


def test_upload_rejects_oversize_content(client, upload_case):
    assert upload(client, b' ' * (20 * 1024 * 1024 + 1)).status_code == 413
    assert uploaded_metadata() is None


def test_upload_requires_admin_and_csrf(client, app, upload_case):
    login(client, upload_case[1])
    assert upload(client).status_code == 302
    assert client.delete(ENDPOINT, json={'revision': ''}).status_code == 302
    login(client, upload_case[0])
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert upload(client).status_code == 400
        assert client.delete(ENDPOINT, json={'revision': ''}).status_code == 400
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    assert uploaded_metadata() is None


def test_upload_only_automation_and_removal_prerequisites(client, db_session, upload_case):
    metadata = upload(client).json['catalogue']
    response = client.post('/admin/settings', json={'section': 'requests', 'settings': {
        'autoFulfillTorrentRequests': True, 'torrentCatalogueUrls': '',
        'torrentDestinationLibraryUuid': upload_case[3].uuid}})
    assert response.status_code == 200
    assert client.delete(ENDPOINT, json={'revision': metadata['sha256']}).status_code == 400
    assert uploaded_metadata() is not None
    page = client.get('/admin/settings?section=requests')
    assert page.status_code == 200 and b'Browser catalogue' in page.data
    assert b'Catalogue JSON file' in page.data and b'magnet:?' not in page.data
    checked = client.post('/admin/torrent-catalogues/test', json={'urls': ''})
    assert checked.status_code == 200 and checked.json['results'][0]['ok'] is True
    assert client.post('/admin/settings', json={'section': 'requests', 'settings': {
        'autoFulfillTorrentRequests': False}}).status_code == 200
    assert client.delete(ENDPOINT, json={'revision': metadata['sha256']}).status_code == 200


def test_upload_migration_is_repeatable_and_reversible(db_session):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from sharewarez import db
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261117_39_uploaded_catalogue.py'
    spec = importlib.util.spec_from_file_location('upload_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = 'upload_' + uuid4().hex
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert 'uploaded_torrent_catalogues' in inspect(connection).get_table_names()
                migration.downgrade()
                assert 'uploaded_torrent_catalogues' not in inspect(connection).get_table_names()
        finally:
            transaction.rollback()
