"""Private, persistent torrent attachments independent of game mounts."""
import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from flask import current_app, has_app_context

# Shared by every web/worker/backup process connected to the same database.
SOURCE_STORAGE_LOCK = 0x53575A544F52524E


def acquire_source_mutation_lock(game_uuid=None):
    """Hold storage shared until commit/rollback; serialize a game's source count.

    Always acquire this before the parent row lock. Backup/restore takes the
    exclusive advisory lock, so no committed reference can change mid-snapshot.
    """
    from sqlalchemy import select, text
    from sharewarez import db
    from sharewarez.models import Game
    with db.session.no_autoflush:
        db.session.execute(text('SELECT pg_advisory_xact_lock_shared(:key)'), {'key': SOURCE_STORAGE_LOCK})
    if game_uuid:
        return db.session.execute(select(Game).where(Game.uuid == game_uuid).with_for_update()).scalar_one_or_none()
    return None


@contextmanager
def exclusive_source_storage(database_uri):
    """Quiesce source mutations and maintenance across all application processes."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    engine = create_engine(database_uri, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': SOURCE_STORAGE_LOCK})
            try:
                yield connection
            finally:
                # NullPool also closes the physical connection after an error,
                # releasing the session lock even if the unlock cannot run.
                if not connection.invalidated:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': SOURCE_STORAGE_LOCK})
    finally:
        engine.dispose()


def private_directory(directory):
    """Prevent configuration from exposing attachments as public/game/cache files."""
    root = Path(directory).expanduser().resolve()
    protected = [Path(__file__).resolve().parents[1] / 'static']
    config = current_app.config if has_app_context() else os.environ
    if has_app_context() and current_app.static_folder:
        protected.append(Path(current_app.static_folder))
    for key in ('DOWNLOAD_CACHE_DIR', 'DATA_FOLDER_WAREZ', 'BASE_FOLDER_WINDOWS', 'BASE_FOLDER_POSIX'):
        if config.get(key):
            protected.append(Path(config[key]))
    if any(root.is_relative_to(path.expanduser().resolve()) for path in protected):
        raise ValueError('Torrent storage must be outside public assets, game mounts, and the download cache.')
    return root


def storage_directory():
    directory = Path(current_app.config.get('TORRENT_STORAGE_DIR') or
                     os.getenv('TORRENT_STORAGE_DIR') or
                     Path(current_app.instance_path) / 'torrent_sources')
    directory = private_directory(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def attachment_path(key):
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}\.torrent', key):
        raise ValueError('Invalid attachment key.')
    path = storage_directory() / key
    if path.is_symlink():
        raise ValueError('Invalid attachment path.')
    return path


def store_attachment(data):
    key = uuid4().hex + '.torrent'
    target = attachment_path(key)
    temporary = target.with_suffix('.pending')
    try:
        with temporary.open('xb') as output:
            os.chmod(temporary, 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return key


def verified_attachment(source):
    path = attachment_path(source.storage_key)
    if not path.is_file() or path.stat().st_size != source.file_bytes:
        raise FileNotFoundError('Torrent attachment unavailable.')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != source.file_sha256:
        raise FileNotFoundError('Torrent attachment failed integrity validation.')
    return data


def cleanup_unreferenced(keys=None, *, grace_seconds=86400):
    """Call after successful mutations and from scheduled maintenance.

    Grace protects uploads finalized before their database transaction commits.
    Failed cleanup is safe to retry without removing referenced attachments.
    """
    if 'sqlalchemy' in current_app.extensions:
        acquire_source_mutation_lock()
    if keys is None:
        from sqlalchemy import select
        from sharewarez import db
        from sharewarez.models import GameTorrentSource
        keys = db.session.execute(select(GameTorrentSource.storage_key).where(
            GameTorrentSource.storage_key.isnot(None))).scalars().all()
    referenced = set(keys)
    cutoff = time.time() - grace_seconds
    removed = 0
    for path in storage_directory().iterdir():
        if path.suffix not in ('.torrent', '.pending', '.restore') or path.name in referenced or path.is_symlink():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            current_app.logger.warning('Torrent attachment cleanup failed; maintenance will retry.')
    return removed
