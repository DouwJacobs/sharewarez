"""Validated PostgreSQL backup and restore tooling."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlparse

from config import Config
from sharewarez.utils.migrations import current_revision


def _connection(database_uri):
    parsed = urlparse(database_uri)
    if parsed.scheme not in {'postgresql', 'postgres'} or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('Backups require a complete PostgreSQL DATABASE_URL.')
    env = os.environ.copy()
    if parsed.password:
        env['PGPASSWORD'] = unquote(parsed.password)
    args = [
        '--host', parsed.hostname, '--port', str(parsed.port or 5432),
        '--username', unquote(parsed.username or 'postgres'),
        '--dbname', unquote(parsed.path.lstrip('/')),
    ]
    return args, env, unquote(parsed.path.lstrip('/'))


def _run(command, env, *, capture=False):
    try:
        return subprocess.run(
            command, env=env, check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f'Required PostgreSQL utility is not installed: {command[0]}') from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or '').strip() if capture else ''
        raise RuntimeError(f'{command[0]} failed{f": {detail}" if detail else ""}') from exc


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def backup_directory(path=None):
    directory = Path(path or os.getenv('BACKUP_DIR', '/backups')).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def verify_backup(path):
    dump_path = Path(path).resolve()
    if not dump_path.is_file():
        raise ValueError(f'Backup does not exist: {dump_path}')
    result = _run(['pg_restore', '--list', str(dump_path)], os.environ.copy(), capture=True)
    if not result.stdout or '; Archive created at ' not in result.stdout:
        raise RuntimeError('PostgreSQL archive validation returned an invalid catalog.')
    manifest_path = dump_path.with_suffix('.json')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('sha256') != _sha256(dump_path):
            raise RuntimeError('Backup checksum does not match its manifest.')
    return True


def prune_backups(directory=None, retain=None):
    directory = backup_directory(directory)
    retain = int(retain if retain is not None else os.getenv('BACKUP_RETENTION_COUNT', '10'))
    if retain < 1:
        raise ValueError('Backup retention must be at least 1.')
    backups = sorted(
        directory.glob('gamelibrary-*.dump'),
        key=lambda item: (item.stat().st_mtime_ns, item.name), reverse=True,
    )
    removed = []
    for dump_path in backups[retain:]:
        manifest_path = dump_path.with_suffix('.json')
        dump_path.unlink()
        if manifest_path.exists():
            manifest_path.unlink()
        removed.append(dump_path.name)
    return removed


def create_backup(database_uri=None, directory=None, *, reason='manual', retain=None):
    database_uri = database_uri or Config.SQLALCHEMY_DATABASE_URI
    connection_args, env, database_name = _connection(database_uri)
    directory = backup_directory(directory)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    safe_reason = ''.join(char if char.isalnum() or char in '-_' else '-' for char in reason)[:40]
    dump_path = directory / f'gamelibrary-{timestamp}-{safe_reason}.dump'
    temporary_path = dump_path.with_suffix('.dump.partial')
    try:
        _run([
            'pg_dump', '--format=custom', '--compress=6', '--no-owner',
            '--no-privileges', '--file', str(temporary_path), *connection_args,
        ], env)
        verify_backup(temporary_path)
        temporary_path.replace(dump_path)
        manifest = {
            'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
            'database': database_name, 'reason': reason,
            'alembic_revision': current_revision(database_uri),
            'size': dump_path.stat().st_size, 'sha256': _sha256(dump_path),
            'filename': dump_path.name,
        }
        dump_path.with_suffix('.json').write_text(
            json.dumps(manifest, indent=2) + '\n', encoding='utf-8'
        )
        verify_backup(dump_path)
        prune_backups(directory, retain)
        return dump_path
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def restore_backup(path, database_uri=None, *, confirmation=None):
    database_uri = database_uri or Config.SQLALCHEMY_DATABASE_URI
    connection_args, env, database_name = _connection(database_uri)
    if confirmation != database_name:
        raise ValueError(f'Restore confirmation must exactly match database name {database_name!r}.')
    verify_backup(path)
    _run([
        'pg_restore', '--clean', '--if-exists', '--no-owner', '--no-privileges',
        '--exit-on-error', *connection_args, str(Path(path).resolve()),
    ], env)


def _parser():
    parser = argparse.ArgumentParser(description='GameLibrary PostgreSQL backup management')
    subparsers = parser.add_subparsers(dest='command', required=True)
    create = subparsers.add_parser('create')
    create.add_argument('--reason', default='manual')
    create.add_argument('--directory')
    verify = subparsers.add_parser('verify')
    verify.add_argument('path')
    prune = subparsers.add_parser('prune')
    prune.add_argument('--directory')
    prune.add_argument('--retain', type=int)
    restore = subparsers.add_parser('restore')
    restore.add_argument('path')
    restore.add_argument('--confirm', required=True, metavar='DATABASE_NAME')
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == 'create':
        print(create_backup(directory=args.directory, reason=args.reason))
    elif args.command == 'verify':
        verify_backup(args.path)
        print(f'Backup verified: {args.path}')
    elif args.command == 'prune':
        for removed in prune_backups(args.directory, args.retain):
            print(f'Removed: {removed}')
    elif args.command == 'restore':
        restore_backup(args.path, confirmation=args.confirm)
        print('Restore completed successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
