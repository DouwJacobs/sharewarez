"""Admin-visible handoff history records actions without claiming torrent progress."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import g
import pytest
from sqlalchemy import delete
from werkzeug.datastructures import FileStorage

from sharewarez.models import Game, Library, TorrentSourceAccess, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.torrent_service import attach_prepared, prepare_source


def login(client, user):
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


@pytest.fixture
def activity_case(app, db_session, tmp_path):
    marker = uuid4().hex
    app.config['TORRENT_STORAGE_DIR'] = str(tmp_path / 'attachments')
    admin = User(name='activity_admin_' + marker[:8], email=marker + '@admin.test', role='admin', password_hash='unused')
    member = User(name='activity_member_' + marker[:8], email=marker + '@member.test', role='user', password_hash='unused')
    library = Library(name='Activity library ' + marker, platform=LibraryPlatform.PCWIN)
    game = Game(name='Activity game ' + marker, library=library)
    db_session.add_all([admin, member, game])
    db_session.flush()
    torrent = Path(__file__).with_name('fixtures') / 'torrents/public-empty.torrent'
    prepared = [prepare_source('Public magnet', 'magnet:?xt=urn:btih:' + 'd' * 40, public=True),
                prepare_source('Public file', upload=FileStorage(BytesIO(torrent.read_bytes()), filename='public.torrent'), public=True)]
    attach_prepared(game, prepared, admin.id)
    db_session.commit()
    sources = {source.kind: source for source in game.torrent_sources}
    root = f'/games/{game.uuid}/torrent-sources/'
    return admin, member, game, sources, root


def test_only_explicit_magnet_handoffs_are_recorded(client, db_session, activity_case):
    admin, member, game, sources, root = activity_case
    endpoint = root + sources['magnet'].id + '/magnet'
    login(client, member)
    assert client.get(endpoint).status_code == 200  # Read/copy does not claim a click.
    assert db_session.query(TorrentSourceAccess).filter_by(game_uuid=game.uuid).count() == 0
    result = client.post(endpoint)
    assert result.status_code == 200
    event = db_session.query(TorrentSourceAccess).filter_by(game_uuid=game.uuid).one()
    assert event.action == 'magnet_handoff'
    assert event.user_id == member.id and event.user_name == member.name
    assert event.source_label == 'Public magnet' and event.file_bytes is None
    assert event.game_name == game.name
    assert client.get('/admin/manage-downloads?view=torrents').status_code == 302
    login(client, admin)
    page = client.get('/admin/manage-downloads', query_string={'view': 'torrents', 'user': member.name})
    assert page.status_code == 200
    assert game.name.encode() in page.data and b'Magnet link clicked' in page.data
    assert b'magnet:?' not in page.data
    assert game.name.encode() not in client.get('/admin/manage-downloads?view=torrents&action=torrent_file').data


def test_torrent_file_response_records_metadata_not_payload_progress(client, db_session, activity_case):
    admin, member, game, sources, root = activity_case
    endpoint = root + sources['torrent'].id + '/file'
    login(client, member)
    assert client.head(endpoint).status_code == 200
    assert db_session.query(TorrentSourceAccess).filter_by(game_uuid=game.uuid).count() == 0
    response = client.get(endpoint)
    assert response.status_code == 200
    event = db_session.query(TorrentSourceAccess).filter_by(game_uuid=game.uuid).one()
    assert event.action == 'torrent_file' and event.file_bytes == len(response.data)
    # Removing source/game records must retain historical names and actions.
    db_session.execute(delete(Game).where(Game.uuid == game.uuid))
    db_session.commit()
    db_session.expire_all()
    assert event.game_uuid is None and event.source_id is None
    assert event.game_name.startswith('Activity game ')


def test_magnet_handoff_requires_csrf_and_authenticated_source(client, app, db_session, activity_case):
    _, member, game, sources, root = activity_case
    endpoint = root + sources['magnet'].id + '/magnet'
    assert client.post(endpoint).status_code == 302
    login(client, member)
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert client.post(endpoint).status_code == 400
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    assert client.post(root + str(uuid4()) + '/magnet').status_code == 404
    assert db_session.query(TorrentSourceAccess).filter_by(game_uuid=game.uuid).count() == 0


@pytest.mark.parametrize('filters', [{'action': 'completed'}, {'page': '0'}, {'page': 'no'}, {'per_page': '101'}])
def test_admin_torrent_filters_are_bounded(client, activity_case, filters):
    login(client, activity_case[0])
    assert client.get('/admin/manage-downloads', query_string={'view': 'torrents', **filters}).status_code == 400


def test_activity_migration_upgrade_and_downgrade(db_session):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from sharewarez import db
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261117_38_torrent_activity.py'
    spec = importlib.util.spec_from_file_location('torrent_activity_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = 'torrent_activity_' + uuid4().hex
    with db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            connection.execute(text('CREATE TABLE users (id integer PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE games (uuid varchar(36) PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE game_torrent_sources (id varchar(36) PRIMARY KEY)'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert 'torrent_source_accesses' in inspect(connection).get_table_names()
                assert len(inspect(connection).get_foreign_keys('torrent_source_accesses')) == 3
                migration.downgrade()
                assert 'torrent_source_accesses' not in inspect(connection).get_table_names()
        finally:
            transaction.rollback()
