#!/usr/bin/env python3
"""Select affected regressions and run modules concurrently in disposable databases."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

GROUPS = {
    'torrents': ('test_torrent_*.py', 'test_game_requests.py', 'test_background_jobs.py',
                 'test_notification_delivery.py', 'test_routes_games_ext_edit.py', 'test_routes_library.py',
                 'test_routes_downloads_ext_admin.py', 'test_routes_admin_ext_settings.py', 'test_routes_settings.py'),
    'requests': ('test_game_requests.py', 'test_torrent_requests.py', 'test_torrent_admin_controls.py',
                 'test_notifications.py', 'test_notification_delivery.py'),
    'downloads': ('test_*download*.py', 'test_admin_delivery.py', 'test_transfer_*.py', 'test_torrent_activity.py'),
    'library': ('test_*librar*.py', 'test_routes_games*.py', 'test_torrent_game_integration.py', 'test_ui_consistency_routes.py'),
    'settings': ('test_routes*settings.py', 'test_torrent_admin_controls.py', 'test_user_experience.py', 'test_notification_delivery.py'),
    'accounts': ('test_routes_apis_user.py', 'test_utils_auth.py', 'test_routes_settings.py',
                 'test_user_experience.py', 'test_torrent_admin_controls.py', 'test_game_requests.py'),
    'jobs': ('test_background_jobs.py', 'test_scan_worker_process.py', 'test_torrent_requests.py', 'test_notification_delivery.py'),
    'themes': ('test_theme_*.py', 'test_utils_themes.py', 'test_ui_components.py', 'test_ui_consistency_routes.py', 'test_accessibility_audit.py'),
    'migrations': ('test_migrations.py', 'test_init_manager_fresh_database.py', 'test_torrent_*.py'),
}
RULES = (
    ('*torrent*', 'torrents'), ('*game_request*', 'requests'), ('*request_notifications*', 'requests'),
    ('*download*', 'downloads'), ('*library*', 'library'), ('*favorites*', 'library'),
    ('*settings*', 'settings'), ('sharewarez/routes_admin_ext/users.py', 'accounts'),
    ('sharewarez/utils/background_jobs.py', 'jobs'), ('migrations/*', 'migrations'),
    ('sharewarez/setup/default_theme/css/*', 'themes'),
    ('sharewarez/setup/default_theme/js/*', 'themes'),
    ('sharewarez/templates/*', 'themes'),
)
MODEL_GROUPS = {'User': ('accounts', 'requests', 'torrents'),
                'UploadedTorrentCatalogue': ('torrents', 'settings'),
                'GameRequest': ('requests',), 'GameRequestUser': ('requests',),
                'GameTorrentSource': ('torrents', 'library'), 'TorrentSourceAccess': ('torrents', 'downloads')}
FOUNDATIONS = {'config.py', 'asgi.py', 'entrypoint.sh', 'startweb-docker.sh', 'pytest.ini',
               'sharewarez/__init__.py', 'conftest.py', 'requirements.in', 'requirements.txt',
               'requirements-dev.in', 'requirements-dev.txt'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode('utf-8')


def changed_files(base):
    if not base:
        try:
            base = git('merge-base', 'HEAD', 'origin/main').strip()
        except subprocess.CalledProcessError:
            base = 'HEAD'
    tracked = git('diff', '--name-only', '-z', base).split('\0')
    untracked = git('ls-files', '--others', '--exclude-standard', '-z').split('\0')
    return sorted(set(tracked + untracked) - {''}), base


def model_changes(previous, current):
    def definitions(source):
        # Imports or top-level configuration changes fall back to broad validation.
        result = {}
        for node in ast.parse(source).body:
            name = getattr(node, 'name', None)
            if name is None:
                name = ast.dump(node, include_attributes=False)
            result[name] = ast.dump(node, include_attributes=False)
        return result
    old, new = definitions(previous), definitions(current)
    return {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}


def select_modules(paths, all_modules, *, changed_models=None):
    selected, reasons = {'tests/test_version.py'}, []
    full = False
    for raw in paths:
        path = raw.replace('\\', '/')
        if path in FOUNDATIONS:
            full = True
            reasons.append(f'{path}: foundational change → full regression')
            continue
        if path.startswith('tests/test_') and path.endswith('.py'):
            selected.add(path)
            continue
        groups = set()
        if path == 'sharewarez/models.py':
            if not changed_models or any(name not in MODEL_GROUPS for name in changed_models):
                full = True
                reasons.append('models: unknown/shared model change → full regression')
            else:
                for name in changed_models:
                    groups.update(MODEL_GROUPS[name])
        else:
            for pattern, group in RULES:
                if fnmatch.fnmatch(path, pattern):
                    groups.add(group)
        if groups:
            for group in sorted(groups):
                selected.update(module for module in all_modules
                                if any(fnmatch.fnmatch(Path(module).name, pattern) for pattern in GROUPS[group]))
            reasons.append(f'{path}: {", ".join(sorted(groups))}')
        elif path.startswith('docs/') or path.lower().endswith('.md') or path.startswith('.validation/'):
            continue
        elif path in ('VERSION', 'Dockerfile', '.dockerignore', '.gitignore', '.gitattributes', 'docker-compose.yml'):
            selected.update(('tests/test_migrations.py', 'tests/test_init_manager_fresh_database.py'))
        elif path.startswith('scripts/'):
            selected.add('tests/test_validation_workflow.py')
        elif path.startswith('sharewarez/') or path.startswith('migrations/'):
            # Never silently miss an unclassified production change.
            full = True
            reasons.append(f'{path}: no domain mapping → full regression')
        elif path.endswith(('.py', '.sh', '.ini')):
            full = True
            reasons.append(f'{path}: unclassified runtime/configuration change → full regression')
    modules = sorted(set(all_modules) if full else selected.intersection(all_modules))
    return {'modules': modules, 'scope': 'full' if full else 'affected', 'reasons': reasons}


def run_module(module, index, uri, output):
    import psycopg2
    from psycopg2 import sql
    from sqlalchemy.engine import make_url
    url = make_url(uri)
    if not url.drivername.startswith('postgresql') or 'test' not in (url.database or '').lower():
        raise ValueError('Validation requires an explicitly named PostgreSQL test database')
    name = f'gamelibrary_validation_test_{os.getpid()}_{index}'
    admin_uri = url.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False)
    test_uri = url.set(drivername='postgresql', database=name).render_as_string(hide_password=False)
    log_path = output / (Path(module).stem + '.log')
    xml_path = output / (Path(module).stem + '.xml')
    started, created = monotonic(), False
    admin = psycopg2.connect(admin_uri)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created = True
        with psycopg2.connect(test_uri) as connection, connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        env = {**os.environ, 'TEST_DATABASE_URL': test_uri, 'DATABASE_URL': test_uri,
               'SECRET_KEY': 'disposable-validation-only-secret', 'BACKUP_BEFORE_UPGRADE': 'false'}
        with log_path.open('w', encoding='utf-8') as log:
            completed = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-o', 'addopts=', '--tb=short',
                '--disable-warnings', f'--junitxml={xml_path}', module], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT, timeout=600)
        count = sum(1 for _ in ET.parse(xml_path).iter('testcase')) if xml_path.exists() else 0
        return {'module': module, 'exit_code': completed.returncode, 'tests': count,
                'seconds': round(monotonic() - started, 2), 'log': str(log_path)}
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='Run the complete retained suite')
    parser.add_argument('--base', help='Compare committed and working changes with this Git ref')
    parser.add_argument('--plan', action='store_true', help='Print the selected modules without running anything')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error('--workers must be between 1 and 8')
    modules = sorted(str(path.relative_to(ROOT)).replace('\\', '/') for path in (ROOT / 'tests').glob('test_*.py'))
    paths, base = changed_files(args.base)
    changes = None
    if 'sharewarez/models.py' in paths:
        changes = model_changes(git('show', f'{base}:sharewarez/models.py'), (ROOT / 'sharewarez/models.py').read_text())
    plan = select_modules(paths, modules, changed_models=changes)
    if args.full:
        plan.update(modules=modules, scope='full')
    plan.update(base=base, changed_files=paths)
    if args.plan:
        print(json.dumps(plan, indent=2))
        return 0
    uri = os.environ.get('TEST_DATABASE_URL')
    if not uri:
        parser.error('TEST_DATABASE_URL is required; use scripts/quality-gate.sh to provision it')
    output = ROOT / '.validation' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True, exist_ok=True)
    print(f'Running {len(plan["modules"])} {plan["scope"]} modules with {args.workers} isolated workers', flush=True)
    started, results = monotonic(), []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_module, module, index, uri, output): module
                   for index, module in enumerate(plan['modules'])}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as error:
                result = {'module': futures[future], 'exit_code': 1, 'tests': 0, 'seconds': 0,
                          'error': type(error).__name__ + ': validation worker failed'}
            results.append(result)
            state = 'PASS' if result['exit_code'] == 0 else 'FAIL'
            print(f'{state} {result["module"]}: {result["tests"]} tests, {result["seconds"]}s', flush=True)
            if state == 'FAIL' and 'log' in result:
                print('\n'.join(Path(result['log']).read_text(errors='replace').splitlines()[-65:]), flush=True)
    summary = {**plan, 'results': results, 'seconds': round(monotonic() - started, 2),
               'tests': sum(result['tests'] for result in results)}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'Finished {summary["tests"]} tests in {summary["seconds"]}s; details: {output / "summary.json"}')
    return int(any(result['exit_code'] for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
