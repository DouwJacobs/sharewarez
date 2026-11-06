import asyncio
import io
import zipfile

from uuid import uuid4

import pytest

from sharewarez.models import DownloadRequest, Game, GlobalSettings, Library, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.zipstream import async_generate_zipstream_chunks


@pytest.fixture
def package(app, client, db_session, tmp_path):
    app.config.update(DATA_FOLDER_WAREZ=str(tmp_path), BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path))
    root = tmp_path / 'Game'
    root.mkdir()
    (root / 'launcher.exe').write_bytes(b'launcher')
    (root / 'readme.nfo').write_bytes(b'notes')
    (root / 'gamelibrary.json').write_text('{}')
    user = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='user', password_hash='unused', state=True)
    library = Library(name=uuid4().hex, platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library])
    db_session.flush()
    game = Game(name='Package fixture', library_uuid=library.uuid, full_disk_path=str(root), times_downloaded=0)
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.settings = {**(settings.settings or {}), 'archiveCacheMode': 'off'}
    db_session.add(game)
    db_session.commit()
    with client.session_transaction() as state:
        state['_user_id'] = str(user.id)
        state['_fresh'] = True
    return client, game, user, root


def test_nested_payload_prevents_direct_launcher_shortcut(package, db_session):
    client, game, user, root = package
    (root / 'assets').mkdir()
    (root / 'assets' / 'required.bin').write_bytes(b'needed')
    response = client.post(f'/download_game/{game.uuid}')
    assert response.status_code == 302
    link = db_session.query(DownloadRequest).filter_by(user_id=user.id, game_uuid=game.uuid).one()
    assert link.zip_file_path == str(root)
    assert link.delivery_kind == 'live_archive'


def test_bookmarked_get_is_read_only_confirmation(package, db_session):
    client, game, user, root = package
    response = client.get(f'/download_game/{game.uuid}')
    assert response.status_code == 200
    assert b'method="post"' in response.data
    assert client.head(f'/download_game/{game.uuid}').status_code == 200
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 0
    assert db_session.query(Game).filter_by(uuid=game.uuid).one().times_downloaded == 0


def test_live_archive_skips_external_file_symlink(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'game.bin').write_bytes(b'game')
    external = tmp_path / 'private.bin'
    external.write_bytes(b'private')
    (source / 'escaped.bin').symlink_to(external)

    async def collect():
        return b''.join([chunk async for chunk in async_generate_zipstream_chunks(str(source))])

    with zipfile.ZipFile(io.BytesIO(asyncio.run(collect()))) as archive:
        assert archive.namelist() == ['game.bin']

def test_root_file_with_notes_keeps_direct_shortcut(package, db_session):
    client, game, user, root = package
    client.post(f'/download_game/{game.uuid}')
    link = db_session.query(DownloadRequest).filter_by(user_id=user.id).one()
    assert link.zip_file_path == str(root / 'launcher.exe')
    assert link.delivery_kind == 'direct'


def test_missing_source_creates_no_link_or_counter(package, db_session):
    client, game, user, root = package
    (root / 'launcher.exe').unlink()
    (root / 'readme.nfo').unlink()
    (root / 'gamelibrary.json').unlink()
    root.rmdir()
    response = client.post(f'/download_game/{game.uuid}')
    assert response.status_code == 302
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 0
    db_session.refresh(game)
    assert game.times_downloaded == 0


def test_simultaneous_normal_posts_reuse_one_link(package, app, db_session, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sharewarez.routes_downloads_ext import initiate
    client, game, user, root = package
    user_id, game_uuid = user.id, game.uuid
    barrier = Barrier(2)
    original = initiate.create_or_reuse_download

    def synchronized(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(initiate, 'create_or_reuse_download', synchronized)

    def post():
        with app.test_client() as browser:
            with browser.session_transaction() as state:
                state['_user_id'] = str(user_id)
                state['_fresh'] = True
            return browser.post(f'/download_game/{game_uuid}').location

    with ThreadPoolExecutor(max_workers=2) as executor:
        locations = list(executor.map(lambda _: post(), range(2)))
    assert locations[0] == locations[1] and '/download_zip/' in locations[0]
    db_session.expire_all()
    assert db_session.query(DownloadRequest).filter_by(user_id=user_id, game_uuid=game_uuid).count() == 1
    assert db_session.query(Game).filter_by(uuid=game_uuid).one().times_downloaded == 1


def test_post_requires_csrf_and_confirmation_supplies_token(package, app, db_session):
    from bs4 import BeautifulSoup
    client, game, user, root = package
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert client.post(f'/download_game/{game.uuid}').status_code == 400
        assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 0
        confirmation = client.get(f'/download_game/{game.uuid}')
        token = BeautifulSoup(confirmation.data, 'html.parser').select_one('[name=csrf_token]')['value']
        assert client.post(f'/download_game/{game.uuid}', data={'csrf_token': token}).status_code == 302
        assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 1
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_reuse_is_member_game_type_record_and_source_scoped(package, app, db_session):
    from sharewarez.models import GameExtra, GameUpdate
    browser, game, user, root = package
    source = root / 'launcher.exe'
    update = GameUpdate(game_uuid=game.uuid, file_path=str(source), title='Patch', times_downloaded=0)
    extras = [GameExtra(game_uuid=game.uuid, file_path=str(source), times_downloaded=0) for index in range(2)]
    db_session.add_all([update, *extras])
    db_session.commit()
    urls = [f'/download_game/{game.uuid}', f'/download_other/update/{game.uuid}/{update.id}',
            *[f'/download_other/extra/{game.uuid}/{extra.id}' for extra in extras]]
    locations = [browser.post(url).location for url in urls]
    assert len(set(locations)) == 4
    assert [browser.post(url).location for url in urls] == locations
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 4
    other = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='user', password_hash='unused', state=True)
    db_session.add(other)
    db_session.commit()
    with browser.session_transaction() as state:
        state['_user_id'] = str(other.id)
    with app.app_context():
        assert browser.post(urls[0]).location not in locations
    changed = root / 'other.exe'
    changed.write_bytes(b'other')
    game.full_disk_path = str(changed)
    db_session.commit()
    with app.app_context():
        assert browser.post(urls[0]).location not in locations


def test_legacy_duplicate_links_remain_addressable_and_reuse_newest(package, db_session):
    client, game, user, root = package
    from datetime import datetime, timedelta, timezone
    links = [DownloadRequest(user_id=user.id, game_uuid=game.uuid, content_type='game',
             file_location=str(root), zip_file_path=str(root / 'launcher.exe'), status='available',
             request_time=datetime.now(timezone.utc) + timedelta(seconds=index)) for index in range(2)]
    db_session.add_all(links)
    db_session.commit()
    assert client.post(f'/download_game/{game.uuid}').location.endswith(f'/download_zip/{links[1].id}')
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 2
    db_session.refresh(game)
    assert game.times_downloaded == 0


def test_cached_and_live_archives_share_custom_exclusions(package, app, db_session):
    from sharewarez.utils.download_cache import build_source_manifest, _excluded_folder_names
    client, game, user, root = package
    settings = db_session.query(GlobalSettings).first()
    settings.update_folder_name = 'Patches'
    settings.extras_folder_name = 'Bonus'
    db_session.commit()
    for name in ('Patches', 'Bonus', 'updates', 'extras', 'assets'):
        (root / name).mkdir()
        (root / name / 'data.bin').write_bytes(name.encode())
    (root / 'assets' / 'sharewarez.json').write_text('{}')
    (root / 'linked-dir').symlink_to(root / 'assets', target_is_directory=True)
    with app.app_context():
        _, manifest, _ = build_source_manifest(str(root))
        exclusions = sorted(_excluded_folder_names())

    async def collect():
        return b''.join([chunk async for chunk in async_generate_zipstream_chunks(str(root), excluded_folders=exclusions)])

    with zipfile.ZipFile(io.BytesIO(asyncio.run(collect()))) as archive:
        assert archive.namelist() == [entry['relative_path'] for entry in manifest]
        assert set(archive.namelist()) == {'launcher.exe', 'readme.nfo', 'assets/data.bin'}

def test_legacy_asset_without_record_id_reuses_exact_source_link(package, db_session):
    from sharewarez.models import GameUpdate
    client, game, user, root = package
    patch = GameUpdate(game_uuid=game.uuid, file_path=str(root / 'launcher.exe'), times_downloaded=0)
    old = DownloadRequest(user_id=user.id, game_uuid=game.uuid, content_type='update',
                          file_location=patch.file_path, zip_file_path=patch.file_path, status='available')
    db_session.add_all([patch, old])
    db_session.commit()
    response = client.post(f'/download_other/update/{game.uuid}/{patch.id}')
    assert response.location.endswith(f'/download_zip/{old.id}')
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 1
    db_session.refresh(patch)
    assert patch.times_downloaded == 0

def test_asset_get_is_confirmation_and_missing_asset_post_cannot_create(package, db_session):
    from sharewarez.models import GameUpdate
    client, game, user, root = package
    patch = GameUpdate(game_uuid=game.uuid, file_path=str(root / 'launcher.exe'), title='Patch', times_downloaded=0)
    db_session.add(patch)
    db_session.commit()
    url = f'/download_other/update/{game.uuid}/{patch.id}'
    assert client.get(url).status_code == 200
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 0
    (root / 'launcher.exe').unlink()
    assert client.post(url).status_code == 302
    assert db_session.query(DownloadRequest).filter_by(user_id=user.id).count() == 0
    db_session.refresh(patch)
    assert patch.times_downloaded == 0

def test_nested_game_initiation_builds_complete_cached_zip(package, app, db_session, tmp_path):
    from types import SimpleNamespace
    from sharewarez.utils.download_cache import build_archive, resolved_archive_path
    client, game, user, root = package
    (root / 'assets').mkdir()
    (root / 'assets' / 'required.bin').write_bytes(b'needed')
    settings = db_session.query(GlobalSettings).first()
    settings.settings = {**settings.settings, 'archiveCacheMode': 'prefer', 'archiveCacheMinFreeGb': 0}
    app.config['DOWNLOAD_CACHE_DIR'] = str(tmp_path / 'cache')
    db_session.commit()
    assert client.post(f'/download_game/{game.uuid}').location.endswith('/downloads')
    link = db_session.query(DownloadRequest).filter_by(user_id=user.id).one()
    assert link.delivery_kind == 'cached_archive' and link.status == 'processing'
    archive = link.archive
    context = SimpleNamespace(job_id=archive.build_job_id, heartbeat=lambda *args: None, check_cancelled=lambda: None)
    build_archive(context, archive.id)
    db_session.refresh(link)
    db_session.refresh(archive)
    assert link.status == 'available'
    with zipfile.ZipFile(resolved_archive_path(archive)) as result:
        assert set(result.namelist()) == {'launcher.exe', 'assets/required.bin', 'readme.nfo'}
        assert result.read('assets/required.bin') == b'needed'