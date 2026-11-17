import hashlib
from pathlib import Path
import pytest
from sharewarez.utils.torrent_backup import create_sidecar, restore_sidecar, verify_sidecar, sidecar


def test_attachment_backup_restore_and_tamper(tmp_path, monkeypatch):
    storage = tmp_path / 'sources'
    storage.mkdir()
    monkeypatch.setenv('TORRENT_STORAGE_DIR', str(storage))
    name = 'a' * 32 + '.torrent'
    content = b'original torrent bytes'
    (storage / name).write_bytes(content)
    dump = tmp_path / 'example.dump'
    digest = create_sidecar(dump)
    assert verify_sidecar(dump, digest) == {name: hashlib.sha256(content).hexdigest()}
    (storage / name).unlink()
    restore_sidecar(dump, digest)
    assert (storage / name).read_bytes() == content
    sidecar(dump).write_bytes(b'tampered')
    with pytest.raises(RuntimeError, match='checksum'):
        verify_sidecar(dump, digest)


def test_attachment_backup_refuses_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv('TORRENT_STORAGE_DIR', str(tmp_path))
    target = tmp_path / 'outside'
    target.write_bytes(b'secret')
    (tmp_path / ('b' * 32 + '.torrent')).symlink_to(target)
    with pytest.raises(ValueError, match='Unsafe'):
        create_sidecar(tmp_path / 'example.dump')


def test_backup_checks_database_references_and_omits_orphans(tmp_path, monkeypatch):
    monkeypatch.setenv('TORRENT_STORAGE_DIR', str(tmp_path / 'sources'))
    storage = tmp_path / 'sources'
    storage.mkdir()
    name = 'c' * 32 + '.torrent'
    content = b'referenced file'
    sources = {name: dict(file_bytes=len(content), file_sha256=hashlib.sha256(content).hexdigest())}
    dump = tmp_path / 'example.dump'
    with pytest.raises(FileNotFoundError):
        create_sidecar(dump, sources)
    (storage / name).write_bytes(b'corrupt content')
    with pytest.raises(ValueError, match='integrity'):
        create_sidecar(dump, sources)
    (storage / name).write_bytes(content)
    (storage / ('d' * 32 + '.torrent')).write_bytes(b'orphan')
    digest = create_sidecar(dump, sources)
    assert verify_sidecar(dump, digest) == {name: hashlib.sha256(content).hexdigest()}


def test_backup_rejects_unsafe_database_storage_key(tmp_path, monkeypatch):
    monkeypatch.setenv('TORRENT_STORAGE_DIR', str(tmp_path / 'sources'))
    with pytest.raises(ValueError, match='Unsafe'):
        create_sidecar(tmp_path / 'backup.dump', {'../' + 'e' * 32 + '.torrent': {}})


def test_restore_can_retry_after_a_crashed_temporary_writer(tmp_path, monkeypatch):
    storage = tmp_path / 'sources'
    storage.mkdir()
    monkeypatch.setenv('TORRENT_STORAGE_DIR', str(storage))
    name = 'f' * 32 + '.torrent'
    (storage / name).write_bytes(b'original')
    dump = tmp_path / 'backup.dump'
    digest = create_sidecar(dump)
    (storage / name).unlink()
    # Old releases used a predictable .restore temporary path.
    (storage / (name + '.restore')).write_bytes(b'interrupted')
    restore_sidecar(dump, digest)
    assert (storage / name).read_bytes() == b'original'
    assert not list(storage.glob('*.pending'))
