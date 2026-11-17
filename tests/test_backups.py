import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from contextlib import nullcontext

from sharewarez import backups


DATABASE_URI = 'postgresql://backup-user:backup-password@db.example:5433/gamelibrary'


@pytest.fixture(autouse=True)
def fake_source_coordination(monkeypatch):
    # These unit cases fake PostgreSQL utilities; real advisory locking is
    # exercised separately against the isolated PostgreSQL test database.
    monkeypatch.setattr(backups, 'exclusive_source_storage', lambda uri: nullcontext(None))
    monkeypatch.setattr(backups, 'referenced_attachments', lambda connection: {})


def fake_postgres_tools(command, env, *, capture=False):
    if command[0] == 'pg_dump':
        output = Path(command[command.index('--file') + 1])
        output.write_bytes(b'postgres-custom-archive')
        return SimpleNamespace(stdout=None, stderr=None)
    return SimpleNamespace(stdout='; Archive created at 2026-08-09\n', stderr='')


def test_create_backup_validates_manifest_and_prunes(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    monkeypatch.setattr(backups, 'current_revision', lambda uri: 'revision-test')

    first = backups.create_backup(DATABASE_URI, tmp_path, reason='manual', retain=1)
    second = backups.create_backup(DATABASE_URI, tmp_path, reason='pre upgrade', retain=1)

    assert not first.exists()
    assert second.exists()
    manifest = json.loads(second.with_suffix('.json').read_text(encoding='utf-8'))
    assert manifest['database'] == 'gamelibrary'
    assert manifest['reason'] == 'pre upgrade'
    assert manifest['alembic_revision'] == 'revision-test'
    assert manifest['sha256'] == backups._sha256(second)
    assert backups.verify_backup(second) is True


def test_verify_rejects_tampered_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    dump_path = tmp_path / 'gamelibrary-test.dump'
    dump_path.write_bytes(b'original')
    dump_path.with_suffix('.json').write_text(json.dumps({
        'sha256': backups._sha256(dump_path),
    }), encoding='utf-8')
    dump_path.write_bytes(b'tampered')

    with pytest.raises(RuntimeError, match='checksum'):
        backups.verify_backup(dump_path)


def test_restore_requires_exact_database_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    dump_path = tmp_path / 'gamelibrary-test.dump'
    dump_path.write_bytes(b'archive')

    with pytest.raises(ValueError, match='exactly match'):
        backups.restore_backup(dump_path, DATABASE_URI, confirmation='wrong-database')


def test_restore_validates_then_invokes_pg_restore(tmp_path, monkeypatch):
    commands = []

    def record(command, env, *, capture=False):
        commands.append(command)
        return SimpleNamespace(stdout='; Archive created at 2026-08-09\n', stderr='')

    monkeypatch.setattr(backups, '_run', record)
    dump_path = tmp_path / 'gamelibrary-test.dump'
    dump_path.write_bytes(b'archive')

    backups.restore_backup(dump_path, DATABASE_URI, confirmation='gamelibrary')

    assert commands[0][:2] == ['pg_restore', '--list']
    assert '--clean' in commands[1]
    assert '--exit-on-error' in commands[1]
    assert '--single-transaction' in commands[1]


def test_failed_sidecar_never_publishes_database_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    def fail_sidecar(*args):
        raise OSError('attachment unreadable')
    monkeypatch.setattr(backups, 'create_sidecar', fail_sidecar)
    with pytest.raises(OSError, match='unreadable'):
        backups.create_backup(DATABASE_URI, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_dump_is_published_only_after_manifest_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    monkeypatch.setattr(backups, 'current_revision', lambda uri: 'revision-test')
    original_replace = Path.replace
    published = []
    def checked_replace(source, target):
        target = Path(target)
        if target.parent == tmp_path:
            published.append(target.suffix)
            if target.suffix == '.dump':
                assert target.with_suffix('.json').is_file()
                assert backups.sidecar(target).is_file()
        return original_replace(source, target)
    monkeypatch.setattr(Path, 'replace', checked_replace)
    backup = backups.create_backup(DATABASE_URI, tmp_path)
    assert published == ['.zip', '.json', '.dump']
    assert backups.verify_backup(backup)


def test_publication_failure_removes_partial_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    monkeypatch.setattr(backups, 'current_revision', lambda uri: 'revision-test')
    original_replace = Path.replace
    def fail_manifest(source, target):
        if Path(target).parent == tmp_path and Path(target).suffix == '.json':
            raise OSError('publication failed')
        return original_replace(source, target)
    monkeypatch.setattr(Path, 'replace', fail_manifest)
    with pytest.raises(OSError, match='publication failed'):
        backups.create_backup(DATABASE_URI, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_torrent_schema_requires_complete_backup_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', lambda *a, **k: SimpleNamespace(
        stdout='; Archive created at test\n123; 1259 1 TABLE public game_torrent_sources owner\n'))
    dump = tmp_path / 'incomplete.dump'
    dump.write_bytes(b'archive')
    with pytest.raises(RuntimeError, match='manifest'):
        backups.verify_backup(dump)
    dump.with_suffix('.json').write_text(json.dumps({'sha256': backups._sha256(dump)}))
    with pytest.raises(RuntimeError, match='attachment checksum'):
        backups.verify_backup(dump)


def test_historical_database_only_backup_still_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, '_run', fake_postgres_tools)
    dump = tmp_path / 'historical.dump'
    dump.write_bytes(b'archive')
    assert backups.verify_backup(dump)


def test_backup_rejects_non_postgresql_database():
    with pytest.raises(ValueError, match='PostgreSQL'):
        backups.create_backup('sqlite:///local.db')
