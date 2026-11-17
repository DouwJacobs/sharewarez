import os
import time
from types import SimpleNamespace
import pytest
from flask import Flask
from sharewarez.utils.torrent_storage import store_attachment, verified_attachment, attachment_path, cleanup_unreferenced


def test_attachment_integrity_and_reference_aware_cleanup(tmp_path):
    app = Flask(__name__)
    app.config['TORRENT_STORAGE_DIR'] = str(tmp_path)
    with app.app_context():
        kept = store_attachment(b'kept original bytes')
        old = store_attachment(b'orphan bytes')
        fresh = store_attachment(b'in flight bytes')
        for key in (kept, old):
            os.utime(attachment_path(key), (time.time() - 90000,) * 2)
        assert cleanup_unreferenced([kept]) == 1
        assert attachment_path(kept).is_file() and attachment_path(fresh).is_file()
        assert not attachment_path(old).exists()
        import hashlib
        source = SimpleNamespace(storage_key=kept, file_bytes=len(b'kept original bytes'),
                                 file_sha256=hashlib.sha256(b'kept original bytes').hexdigest())
        assert verified_attachment(source) == b'kept original bytes'
        attachment_path(kept).write_bytes(b'x' * source.file_bytes)
        with pytest.raises(FileNotFoundError, match='integrity'):
            verified_attachment(source)
        with pytest.raises(ValueError):
            attachment_path('../outside')


@pytest.mark.parametrize('path', [None, '', '   '])
def test_pathless_local_metadata_never_probes_working_directory(path, monkeypatch):
    from sharewarez.utils import local_metadata
    def forbidden(*args, **kwargs):
        raise AssertionError('Pathless metadata must not access the filesystem')
    monkeypatch.setattr(local_metadata.os.path, 'isdir', forbidden)
    monkeypatch.setattr(local_metadata.os.path, 'exists', forbidden)
    assert local_metadata.read_local_metadata(path) is None
    assert local_metadata.write_local_metadata(path) is False
    assert local_metadata.has_local_metadata(path) is False
    assert local_metadata.delete_local_metadata(path) is True
    assert local_metadata.get_local_cover_path(path) is None
    assert local_metadata.get_local_screenshots(path) == []
    assert local_metadata.has_local_images(path) is False


@pytest.mark.parametrize('key', ['DATA_FOLDER_WAREZ', 'DOWNLOAD_CACHE_DIR'])
def test_attachment_storage_rejects_game_mounts_and_cache(tmp_path, key):
    from sharewarez.utils.torrent_storage import storage_directory
    app = Flask(__name__)
    app.config[key] = str(tmp_path / 'protected')
    app.config['TORRENT_STORAGE_DIR'] = str(tmp_path / 'protected' / 'torrents')
    with app.app_context(), pytest.raises(ValueError, match='outside'):
        storage_directory()
    assert not (tmp_path / 'protected').exists()


def test_attachment_storage_rejects_public_static_folder(tmp_path):
    from sharewarez.utils.torrent_storage import storage_directory
    app = Flask(__name__, static_folder=str(tmp_path / 'public'))
    app.config['TORRENT_STORAGE_DIR'] = str(tmp_path / 'public' / 'torrents')
    with app.app_context(), pytest.raises(ValueError, match='outside'):
        storage_directory()


def test_failed_cleanup_is_retryable_and_preserves_references(tmp_path, monkeypatch):
    from pathlib import Path
    app = Flask(__name__)
    app.config['TORRENT_STORAGE_DIR'] = str(tmp_path)
    with app.app_context():
        key = store_attachment(b'orphan')
        os.utime(attachment_path(key), (time.time() - 90000,) * 2)
        with monkeypatch.context() as patcher:
            def deny_unlink(path, *args, **kwargs):
                raise PermissionError('simulated temporary failure')
            patcher.setattr(Path, 'unlink', deny_unlink)
            assert cleanup_unreferenced([]) == 0
        assert attachment_path(key).exists()
        assert cleanup_unreferenced([key]) == 0
        assert cleanup_unreferenced([]) == 1


def test_backup_exclusive_lock_blocks_source_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sharewarez import db
    from sharewarez.utils.torrent_storage import exclusive_source_storage, acquire_source_mutation_lock
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=os.environ['TEST_DATABASE_URL'])
    db.init_app(app)
    started, acquired = Event(), Event()
    def mutation():
        with app.app_context():
            started.set()
            acquire_source_mutation_lock()
            acquired.set()
            db.session.rollback()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with exclusive_source_storage(os.environ['TEST_DATABASE_URL']):
            future = pool.submit(mutation)
            assert started.wait(5)
            assert not acquired.wait(.2)
        future.result(timeout=5)
    assert acquired.is_set()
