from types import SimpleNamespace
from uuid import uuid4
import zipfile

from flask import Flask
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import (
    BackgroundJob, DownloadArchive, DownloadRequest, Game, Library, User,
)
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.download_cache import (
    build_archive, build_source_manifest, ensure_cache_root, request_resumable_archive,
)


def cache_app(source, cache_dir):
    app = Flask(__name__, static_folder=str(source.parent / 'static'))
    app.config.update(
        DATA_FOLDER_WAREZ=str(source), BASE_FOLDER_POSIX=str(source),
        BASE_FOLDER_WINDOWS='', DOWNLOAD_CACHE_DIR=str(cache_dir),
    )
    return app


def test_manifest_is_deterministic_and_excludes_metadata(tmp_path):
    source = tmp_path / 'game'
    source.mkdir()
    (source / 'part2.rar').write_bytes(b'two')
    (source / 'part1.rar').write_bytes(b'one')
    (source / 'sharewarez.json').write_text('{}', encoding='utf-8')
    updates = source / 'Updates'
    updates.mkdir()
    (updates / 'patch.zip').write_bytes(b'patch')
    app = cache_app(source, tmp_path / 'cache')
    settings = SimpleNamespace(update_folder_name='Updates', extras_folder_name='Extras')

    with app.app_context():
        first = build_source_manifest(str(source), settings)
        second = build_source_manifest(str(source), settings)

    assert first[0] == second[0]
    assert [item['relative_path'] for item in first[1]] == ['part1.rar', 'part2.rar']
    assert first[2] == 6


def test_cache_root_is_private_and_created(tmp_path):
    source = tmp_path / 'game'
    source.mkdir()
    cache_dir = tmp_path / 'private-cache'
    app = cache_app(source, cache_dir)

    with app.app_context():
        assert ensure_cache_root() == cache_dir.resolve()

    assert cache_dir.is_dir()


def _cache_download_fixture(db_session, app, tmp_path, *, suffix='one'):
    unique = uuid4().hex[:8]
    source = tmp_path / f'game-{suffix}'
    source.mkdir()
    (source / 'part01.bin').write_bytes(b'first-part')
    (source / 'part02.bin').write_bytes(b'second-part')
    app.config.update(
        DATA_FOLDER_WAREZ=str(tmp_path), BASE_FOLDER_POSIX=str(tmp_path),
        BASE_FOLDER_WINDOWS='', DOWNLOAD_CACHE_DIR=str(tmp_path / 'cache'),
    )
    library = Library(name=f'Cache library {suffix}', platform=LibraryPlatform.PCWIN)
    user = User(
        user_id=str(uuid4()), name=f'Cache user {suffix} {unique}',
        email=f'cache-{suffix}-{uuid4().hex[:8]}@example.test', role='user',
        is_email_verified=True,
    )
    user.set_password('test-password')
    db_session.add_all([library, user])
    db_session.flush()
    game = Game(name=f'Cache game {suffix}', library_uuid=library.uuid, full_disk_path=str(source))
    db_session.add(game)
    db_session.flush()
    download_request = DownloadRequest(
        user_id=user.id, game_uuid=game.uuid, file_location=str(source),
        status='pending', download_size=20,
    )
    db_session.add(download_request)
    db_session.commit()
    return source, user, game, download_request


def test_directory_request_queues_one_deduplicated_archive(db_session, app, tmp_path):
    source, user, game, first_request = _cache_download_fixture(db_session, app, tmp_path)

    first_archive = request_resumable_archive(first_request, 'cache-game.zip')
    db_session.commit()
    second_request = DownloadRequest(
        user_id=user.id, game_uuid=game.uuid, file_location=str(source),
        status='pending', download_size=20,
    )
    db_session.add(second_request)
    db_session.commit()
    second_archive = request_resumable_archive(second_request, 'cache-game.zip')
    db_session.commit()

    assert first_archive.id == second_archive.id
    assert first_request.status == second_request.status == 'processing'
    assert first_request.delivery_kind == second_request.delivery_kind == 'cached_archive'
    assert db_session.scalar(
        select(DownloadArchive).where(DownloadArchive.cache_key == first_archive.cache_key)
    ) is not None
    jobs = [
        job for job in db_session.execute(
            select(BackgroundJob).where(BackgroundJob.task_name == 'download.archive.build')
        ).scalars()
        if job.payload.get('archive_id') == first_archive.id
    ]
    assert len(jobs) == 1


def test_archive_build_publishes_valid_zip_and_marks_request_ready(db_session, app, tmp_path):
    source, _user, _game, download_request = _cache_download_fixture(
        db_session, app, tmp_path, suffix='build',
    )
    archive = request_resumable_archive(download_request, 'cache-build.zip')
    db_session.commit()
    heartbeats = []
    context = SimpleNamespace(
        job_id=archive.build_job_id,
        heartbeat=lambda progress, message: heartbeats.append((progress, message)),
        check_cancelled=lambda: None,
    )

    result = build_archive(context, archive.id)
    db_session.refresh(archive)
    db_session.refresh(download_request)
    published = tmp_path / 'cache' / archive.relative_path

    assert result['reused'] is False
    assert archive.state == 'ready'
    assert archive.sha256 and len(archive.sha256) == 64
    assert download_request.status == 'available'
    assert published.is_file()
    with zipfile.ZipFile(published) as prepared:
        assert prepared.namelist() == ['part01.bin', 'part02.bin']
        assert prepared.read('part01.bin') == (source / 'part01.bin').read_bytes()
    assert heartbeats[-1][0] == 100
