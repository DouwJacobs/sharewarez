"""Checksummed private attachment sidecars for PostgreSQL backups."""
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile
from uuid import uuid4

from flask import current_app, has_app_context
from sharewarez.utils.torrent_storage import private_directory


def directory():
    configured = current_app.config.get('TORRENT_STORAGE_DIR') if has_app_context() else None
    fallback = Path(__file__).resolve().parents[2] / 'instance' / 'torrent_sources'
    return private_directory(configured or os.getenv('TORRENT_STORAGE_DIR') or fallback)


def sidecar(path):
    return Path(path).with_suffix('.torrents.zip')


def _file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create_sidecar(dump_path, sources=None):
    """Copy immutable files, checking every database reference when supplied."""
    target = sidecar(dump_path)
    temporary = target.with_suffix('.partial')
    root = directory()
    hashes = {}
    try:
        with temporary.open('xb') as output:
            os.chmod(temporary, 0o600)
            _write_sidecar(output, root, hashes, sources)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return _file_digest(target)


def _write_sidecar(output, root, hashes, sources):
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        if sources is not None and any(not isinstance(key, str) or not re.fullmatch(
            r'[a-f0-9]{32}\.torrent', key,
        ) for key in sources):
            raise ValueError('Unsafe torrent attachment reference in backup database.')
        files = sorted(root / key for key in sources) if sources is not None else sorted(root.glob('*.torrent'))
        for file in files:
            if file.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}\.torrent', file.name):
                raise ValueError('Unsafe torrent attachment in backup storage.')
            content = file.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if sources is not None:
                expected = sources[file.name]
                if len(content) != expected['file_bytes'] or digest != expected['file_sha256']:
                    raise ValueError('Referenced torrent attachment failed backup integrity validation.')
            hashes[file.name] = digest
            archive.writestr(file.name, content)
        archive.writestr('manifest.json', json.dumps(hashes, sort_keys=True))


def referenced_attachments(connection):
    """Read while holding the exclusive storage lock used by the database dump."""
    from sqlalchemy import inspect, text
    if not inspect(connection).has_table('game_torrent_sources'):
        return {}
    rows = connection.execute(text(
        "SELECT storage_key, file_bytes, file_sha256 FROM game_torrent_sources WHERE kind = 'torrent'"
    )).mappings()
    return {row['storage_key']: dict(row) for row in rows}


def verify_sidecar(dump_path, expected):
    path = sidecar(dump_path)
    if not path.is_file() or _file_digest(path) != expected:
        raise RuntimeError('Torrent attachment backup checksum mismatch.')
    with zipfile.ZipFile(path) as archive:
        hashes = json.loads(archive.read('manifest.json'))
        if len(archive.namelist()) != len(hashes) + 1:
            raise RuntimeError('Torrent attachment backup contains unexpected files.')
        for name, digest in hashes.items():
            if not re.fullmatch(r'[a-f0-9]{32}\.torrent', name):
                raise RuntimeError('Unsafe torrent attachment backup path.')
            member = archive.getinfo(name)
            if member.file_size > 10 * 1024 * 1024 or hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RuntimeError('Torrent attachment backup content mismatch.')
    return hashes


def restore_sidecar(dump_path, expected):
    hashes = verify_sidecar(dump_path, expected)
    root = directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with zipfile.ZipFile(sidecar(dump_path)) as archive:
        for name in hashes:
            target = root / name
            if target.is_symlink():
                raise RuntimeError('Unsafe torrent attachment restore target.')
            # A unique pending name permits retry after an interrupted restore;
            # normal attachment maintenance reclaims a crashed writer's temp file.
            temporary = root / (uuid4().hex + '.pending')
            try:
                with temporary.open('xb') as output:
                    os.chmod(temporary, 0o600)
                    output.write(archive.read(name))
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    if os.name != 'nt':
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
