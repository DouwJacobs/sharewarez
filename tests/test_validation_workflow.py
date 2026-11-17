"""Validation must select relevant risks and keep subprocess databases isolated."""
import os
from pathlib import Path

from scripts.validate import model_changes, run_module, select_modules


MODULES = ['tests/test_version.py', 'tests/test_torrent_catalogues.py', 'tests/test_torrent_requests.py',
           'tests/test_torrent_activity.py', 'tests/test_game_requests.py', 'tests/test_utils_auth.py',
           'tests/test_notifications.py', 'tests/test_ui_components.py', 'tests/test_ui_consistency_routes.py',
           'tests/test_migrations.py', 'tests/test_routes_library.py', 'tests/test_scan_safety.py']


def test_torrent_change_includes_request_jobs_and_keeps_unrelated_scan_work_out():
    plan = select_modules(['sharewarez/utils/torrent_catalogues.py'], MODULES)
    assert plan['scope'] == 'affected'
    assert {'tests/test_torrent_catalogues.py', 'tests/test_torrent_requests.py',
            'tests/test_game_requests.py'} <= set(plan['modules'])
    assert 'tests/test_scan_safety.py' not in plan['modules']


def test_unknown_production_and_foundational_changes_cannot_silently_skip_tests():
    for path in ('sharewarez/new_feature.py', 'sharewarez/__init__.py', 'config.py',
                 'asgi.py', 'entrypoint.sh', 'startweb-docker.sh', 'pytest.ini', 'new_server.py'):
        assert select_modules([path], MODULES)['modules'] == sorted(MODULES)


def test_styles_and_docs_do_not_force_the_full_database_suite():
    plan = select_modules(['sharewarez/setup/default_theme/css/requests.css', 'docs/README.md'], MODULES)
    assert plan['scope'] == 'affected'
    assert 'tests/test_ui_components.py' in plan['modules']
    assert 'tests/test_scan_safety.py' not in plan['modules']
    assert select_modules(['docs/README.md'], MODULES)['modules'] == ['tests/test_version.py']


def test_model_diff_selects_account_risks_and_falls_back_for_unknown_models():
    before = 'class User:\n    permission = False\n'
    after = 'class User:\n    permission = True\n'
    changes = model_changes(before, after)
    assert changes == {'User'}
    plan = select_modules(['sharewarez/models.py'], MODULES, changed_models=changes)
    assert plan['scope'] == 'affected'
    assert 'tests/test_utils_auth.py' in plan['modules']
    assert select_modules(['sharewarez/models.py'], MODULES, changed_models={'Unknown'})['scope'] == 'full'


def test_changed_test_runs_itself_and_missing_deleted_tests_do_not_run():
    plan = select_modules(['tests/test_torrent_catalogues.py', 'tests/test_deleted.py'], MODULES)
    assert plan['modules'] == ['tests/test_torrent_catalogues.py', 'tests/test_version.py']


def test_runner_runs_a_real_child_and_removes_its_disposable_database(tmp_path):
    import psycopg2
    from sqlalchemy.engine import make_url
    result = run_module('tests/test_version.py', 9999, os.environ['TEST_DATABASE_URL'], tmp_path)
    assert result['exit_code'] == 0
    assert result['tests'] > 0
    assert Path(result['log']).is_file()
    uri = make_url(os.environ['TEST_DATABASE_URL']).set(drivername='postgresql', database='postgres')
    with psycopg2.connect(uri.render_as_string(hide_password=False)) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT count(*) FROM pg_database WHERE datname = %s',
                       (f'gamelibrary_validation_test_{os.getpid()}_9999',))
        assert cursor.fetchone()[0] == 0


def test_runner_rejects_non_test_database_before_connecting(tmp_path):
    import pytest
    with pytest.raises(ValueError, match='test database'):
        run_module('tests/test_version.py', 9998, 'postgresql://postgres@localhost/production', tmp_path)
