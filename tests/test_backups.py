import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sharewarez import backups


DATABASE_URI = 'postgresql://backup-user:backup-password@db.example:5433/gamelibrary'


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


def test_backup_rejects_non_postgresql_database():
    with pytest.raises(ValueError, match='PostgreSQL'):
        backups.create_backup('sqlite:///local.db')
