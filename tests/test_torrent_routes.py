from io import BytesIO
import os
from uuid import uuid4

import pytest
from flask import Flask
from flask_login import LoginManager
from sharewarez import db
from sharewarez.models import Game, Library, User, GameTorrentSource, DownloadRequest
from sharewarez.platform import LibraryPlatform
from sharewarez.routes_games_ext import games_bp


@pytest.fixture
def torrent_app(tmp_path):
    app = Flask(__name__)
    app.config.update(SECRET_KEY='torrent-test', TESTING=True, SQLALCHEMY_DATABASE_URI=os.environ['TEST_DATABASE_URL'],
                      TORRENT_STORAGE_DIR=str(tmp_path / 'attachments'))
    db.init_app(app)
    login = LoginManager(app)
    login.login_view = None
    @login.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))
    app.register_blueprint(games_bp)
    app.add_url_rule('/library', endpoint='library.library', view_func=lambda: 'Library')
    with app.app_context():
        db.drop_all()
        db.create_all()
        library = Library(name='Torrent tests', platform=LibraryPlatform.PCWIN)
        game = Game(name='Source game', library=library, uuid=str(uuid4()))
        admin = User(name='admin', email='admin@example.test', role='admin', password_hash='unused')
        member = User(name='member', email='member@example.test', role='user', password_hash='unused')
        db.session.add_all([game, admin, member])
        db.session.commit()
        app.config.update(TEST_GAME=game.uuid, TEST_ADMIN=admin.id, TEST_MEMBER=member.id)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def signed_client(app, role='ADMIN'):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(app.config['TEST_' + role])
        session['_fresh'] = True
    return client


def test_magnet_lifecycle_and_no_transfer(torrent_app):
    app = torrent_app
    client = signed_client(app)
    root = f"/games/{app.config['TEST_GAME']}/torrent-sources"
    payload = dict(label='Version 1', magnet='magnet:?xt=urn:btih:' + 'a' * 40, public=True)
    response = client.post(root, json=payload)
    assert response.status_code == 201, response.data
    source = response.json
    assert client.post(root, json=payload).status_code == 200
    assert 'magnet:?' not in client.get(root).get_data(as_text=True)
    member = signed_client(app, 'MEMBER')
    opened = member.get(source['action_url'])
    assert opened.json['magnet'] == payload['magnet']
    assert 'no-store' in opened.headers['Cache-Control']
    assert member.post(root, json=payload).status_code == 403
    endpoint = root + '/' + source['id']
    assert member.patch(endpoint, json=dict(revision=1, label='Unauthorized')).status_code == 403
    assert member.delete(endpoint, json=dict(revision=1, retain_catalog=True)).status_code == 403
    assert client.patch(endpoint, json=dict(revision=9, label='stale')).status_code == 409
    changed = client.patch(endpoint, json=dict(revision=1, label='Version 2', public=True,
                                              magnet='magnet:?xt=urn:btih:' + 'b' * 40))
    assert changed.status_code == 200, changed.data
    assert client.get(source['action_url']).json['magnet'].endswith('b' * 40)
    assert client.delete(endpoint, json=dict(revision=changed.json['revision'])).status_code == 400
    assert client.delete(endpoint, json=dict(revision=changed.json['revision'], retain_catalog=True)).status_code == 200
    with app.app_context():
        assert db.session.query(DownloadRequest).count() == 0
        assert db.session.query(Game).filter_by(uuid=app.config['TEST_GAME']).one().times_downloaded == 0


def test_upload_exact_bytes_and_missing_attachment(torrent_app):
    from sharewarez.utils.torrent_storage import attachment_path
    app = torrent_app
    client = signed_client(app)
    root = f"/games/{app.config['TEST_GAME']}/torrent-sources"
    content = b'd4:infod6:lengthi0e4:name4:game12:piece lengthi16384e6:pieces0:ee'
    response = client.post(root, data=dict(label='Public release', public='1', file=(BytesIO(content), 'release.torrent')))
    assert response.status_code == 201, response.data
    action = response.json['action_url']
    download = signed_client(app, 'MEMBER').get(action)
    assert download.data == content
    assert download.mimetype == 'application/x-bittorrent'
    with app.app_context():
        source = db.session.get(GameTorrentSource, response.json['id'])
        attachment_path(source.storage_key).unlink()
    assert client.get(action).status_code == 404


def test_parent_ownership_and_anonymous_access(torrent_app):
    app = torrent_app
    root = f"/games/{app.config['TEST_GAME']}/torrent-sources"
    assert app.test_client().get(root).status_code == 401
    client = signed_client(app)
    source = client.post(root, json=dict(label='Release', public=True,
                                        magnet='magnet:?xt=urn:btih:' + 'c' * 40)).json
    assert client.get(f"/games/{uuid4()}/torrent-sources/{source['id']}/magnet").status_code == 404


def test_mutations_require_csrf(torrent_app):
    from flask_wtf.csrf import CSRFProtect
    CSRFProtect(torrent_app)
    client = signed_client(torrent_app)
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    response = client.post(root, json=dict(label='Release', public=True,
                                          magnet='magnet:?xt=urn:btih:' + 'c' * 40))
    assert response.status_code == 400
    with torrent_app.app_context():
        assert db.session.query(GameTorrentSource).count() == 0


def test_commit_failure_compensates_uploaded_file(torrent_app, monkeypatch):
    from sharewarez.utils.torrent_storage import storage_directory
    client = signed_client(torrent_app)
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    content = b'd4:infod6:lengthi0e4:name4:game12:piece lengthi16384e6:pieces0:ee'
    def fail_commit():
        raise RuntimeError('simulated commit failure')
    monkeypatch.setattr(db.session, 'commit', fail_commit)
    with pytest.raises(RuntimeError, match='simulated'):
        client.post(root, data=dict(label='Release', public='1', file=(BytesIO(content), 'release.torrent')))
    with torrent_app.app_context():
        assert not list(storage_directory().glob('*.torrent'))
        assert db.session.query(GameTorrentSource).count() == 0


def test_explicit_final_source_game_deletion(torrent_app):
    client = signed_client(torrent_app)
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    source = client.post(root, json=dict(label='Release', public=True,
                                        magnet='magnet:?xt=urn:btih:' + 'd' * 40)).json
    result = client.delete(root + '/' + source['id'], json=dict(revision=1, delete_game=True))
    assert result.status_code == 200, result.data
    assert result.json['deleted_game']
    with torrent_app.app_context():
        assert db.session.query(GameTorrentSource).count() == 0
        assert db.session.query(Game).count() == 0


def test_tracker_variants_and_cross_game_matches_need_confirmation(torrent_app):
    client = signed_client(torrent_app)
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    magnet = 'magnet:?xt=urn:btih:' + 'e' * 40
    first = dict(label='Tracker one', public=True, magnet=magnet + '&tr=https%3A%2F%2Ftracker-one.example%2Fannounce')
    assert client.post(root, json=first).status_code == 201
    variant = {**first, 'label': 'Tracker two', 'magnet': magnet + '&tr=https%3A%2F%2Ftracker-two.example%2Fannounce'}
    assert client.post(root, json=variant).status_code == 400
    assert client.post(root, json={**variant, 'keep_separate': True}).status_code == 201
    with torrent_app.app_context():
        other = Game(name='Other edition', library=db.session.query(Library).first())
        db.session.add(other)
        db.session.commit()
        other_uuid = other.uuid
    other_root = f'/games/{other_uuid}/torrent-sources'
    assert client.post(other_root, json=first).status_code == 400
    assert client.post(other_root, json={**first, 'keep_separate': True}).status_code == 201


def test_failed_replacement_keeps_original_source(torrent_app, monkeypatch):
    from sharewarez.utils.torrent_storage import storage_directory
    client = signed_client(torrent_app)
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    magnet = 'magnet:?xt=urn:btih:' + 'a' * 40
    source = client.post(root, json=dict(label='Original', public=True, magnet=magnet)).json
    content = b'd4:infod6:lengthi0e4:name4:game12:piece lengthi16384e6:pieces0:ee'
    with monkeypatch.context() as patcher:
        def fail_commit():
            raise RuntimeError('replacement commit failed')
        patcher.setattr(db.session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='replacement commit'):
            client.patch(root + '/' + source['id'], data=dict(revision='1', label='Replacement', public='1',
                                                             file=(BytesIO(content), 'replacement.torrent')))
    assert client.get(source['action_url']).json['magnet'] == magnet
    assert client.get(root).json[0]['revision'] == 1
    with torrent_app.app_context():
        assert not list(storage_directory().glob('*.torrent'))


def test_concurrent_uploads_create_one_source_and_one_attachment(torrent_app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sharewarez.routes_games_ext import torrents
    from sharewarez.utils.torrent_storage import storage_directory
    barrier = Barrier(2)
    acquire = torrents.acquire_source_mutation_lock
    def synchronized_acquire(*args, **kwargs):
        barrier.wait(timeout=10)
        return acquire(*args, **kwargs)
    monkeypatch.setattr(torrents, 'acquire_source_mutation_lock', synchronized_acquire)
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    content = b'd4:infod6:lengthi0e4:name4:game12:piece lengthi16384e6:pieces0:ee'
    def upload():
        return signed_client(torrent_app).post(root, data=dict(label='Concurrent release', public='1',
                    file=(BytesIO(content), 'release.torrent'))).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: upload(), range(2)))
    assert sorted(statuses) == [200, 201]
    with torrent_app.app_context():
        assert db.session.query(GameTorrentSource).count() == 1
        assert len(list(storage_directory().glob('*.torrent'))) == 1
    monkeypatch.setattr(torrents, 'acquire_source_mutation_lock', acquire)
    assert signed_client(torrent_app).post(root, data=dict(label='Retry', public='1',
                 file=(BytesIO(content), 'release.torrent'))).status_code == 200


def test_concurrent_last_two_removals_require_catalog_confirmation(torrent_app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sharewarez.routes_games_ext import torrents
    root = f"/games/{torrent_app.config['TEST_GAME']}/torrent-sources"
    client = signed_client(torrent_app)
    sources = [client.post(root, json=dict(label=hash_char, public=True,
                magnet='magnet:?xt=urn:btih:' + hash_char * 40)).json for hash_char in 'ab']
    barrier = Barrier(2)
    acquire = torrents.acquire_source_mutation_lock
    def synchronized_acquire(*args, **kwargs):
        barrier.wait(timeout=10)
        return acquire(*args, **kwargs)
    with monkeypatch.context() as patcher:
        patcher.setattr(torrents, 'acquire_source_mutation_lock', synchronized_acquire)
        def remove(source):
            return signed_client(torrent_app).delete(root + '/' + source['id'],
                json=dict(revision=source['revision'])).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(remove, sources))
    assert sorted(statuses) == [200, 400]
    remaining = client.get(root).json
    assert len(remaining) == 1
    assert client.delete(root + '/' + remaining[0]['id'], json=dict(
        revision=remaining[0]['revision'], retain_catalog=True)).status_code == 200
    with torrent_app.app_context():
        assert db.session.query(Game).count() == 1
        assert db.session.query(GameTorrentSource).count() == 0


def test_attachment_service_persists_a_transient_parent(torrent_app):
    from sharewarez.utils.torrent_service import attach_prepared, prepare_source
    with torrent_app.app_context():
        game = Game(name='Transient source parent', library=db.session.query(Library).first())
        prepared = prepare_source('Public source', 'magnet:?xt=urn:btih:' + 'f' * 40, public=True)
        attach_prepared(game, [prepared], torrent_app.config['TEST_ADMIN'])
        db.session.commit()
        assert game.uuid
        assert len(db.session.get(Game, game.id).torrent_sources) == 1
