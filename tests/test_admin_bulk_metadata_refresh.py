from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from sharewarez.models import Game, Library, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.background_jobs import job_display_name


@pytest.fixture
def bulk_metadata_library(db_session):
    library = Library(
        name=f'Bulk Metadata {uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.flush()
    db_session.add(Game(name='Refresh Me', library_uuid=library.uuid, igdb_id=12345))
    db_session.commit()
    return library


@pytest.fixture
def bulk_metadata_admin(db_session):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'bulk_admin_{suffix}',
        email=f'bulk_admin_{suffix}@example.com',
        password_hash='not-used',
        role='admin',
        user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_library_actions_offer_bulk_metadata_refresh():
    template = Path('sharewarez/templates/admin/admin_manage_libraries.html').read_text(encoding='utf-8')
    javascript = Path('sharewarez/setup/default_theme/js/admin_manage_libs.js').read_text(encoding='utf-8')

    assert 'bulk-refresh-lib-metadata' in template
    assert 'Bulk Refresh Metadata' in template
    assert '/refresh_metadata' in javascript
    assert 'CSRFUtils.getHeaders' in javascript

    route_source = Path('sharewarez/routes_admin_ext/libraries.py').read_text(encoding='utf-8')
    jobs_source = Path('sharewarez/utils/background_jobs.py').read_text(encoding='utf-8')
    assert "enqueue(\n        'library.bulk_metadata_refresh'" in route_source
    assert "@register_task('library.bulk_metadata_refresh')" in jobs_source
    assert 'context.heartbeat(' in jobs_source


def test_bulk_image_refresh_uses_the_tracked_job_queue():
    route_source = Path('sharewarez/routes_admin_ext/libraries.py').read_text(encoding='utf-8')
    jobs_source = Path('sharewarez/utils/background_jobs.py').read_text(encoding='utf-8')

    assert "enqueue(\n        'library.bulk_image_refresh'" in route_source
    assert "@register_task('library.bulk_image_refresh')" in jobs_source
    assert 'Thread(target=run_bulk_refresh' not in route_source
    assert "'job_url': url_for('admin2.background_jobs')" in route_source


def test_background_job_names_are_human_readable():
    assert job_display_name('library.bulk_metadata_refresh') == 'Bulk metadata refresh'
    assert job_display_name('library.bulk_image_refresh') == 'Bulk image refresh'
    assert job_display_name('custom.example_task') == 'Custom Example Task'


@patch('sharewarez.utils.background_jobs.enqueue')
def test_bulk_metadata_refresh_queues_every_library_game(
    mock_enqueue,
    client,
    bulk_metadata_admin,
    bulk_metadata_library,
):
    mock_enqueue.return_value.id = 'job-123'
    with client.session_transaction() as session:
        session['_user_id'] = str(bulk_metadata_admin.id)
        session['_fresh'] = True

    response = client.post(
        f'/admin/api/library/{bulk_metadata_library.uuid}/refresh_metadata'
    )

    assert response.status_code == 202
    assert response.get_json()['games_queued'] == 1
    assert response.get_json()['job_id'] == 'job-123'
    mock_enqueue.assert_called_once_with(
        'library.bulk_metadata_refresh',
        {'library_uuid': str(bulk_metadata_library.uuid)},
        max_attempts=2,
        created_by_id=bulk_metadata_admin.id,
    )
