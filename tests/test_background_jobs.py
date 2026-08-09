from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from sharewarez import db
from sharewarez.models import BackgroundJob, LibraryScanSchedule, LibraryScanState, User
from sharewarez.utils.background_jobs import (
    claim_next,
    enqueue,
    execute,
    recover_stale_jobs,
)


@pytest.fixture(autouse=True)
def clean_background_jobs(db_session):
    db_session.execute(delete(LibraryScanSchedule))
    db_session.execute(delete(LibraryScanState))
    db_session.execute(delete(BackgroundJob))
    db_session.commit()
    yield
    db_session.execute(delete(LibraryScanSchedule))
    db_session.execute(delete(LibraryScanState))
    db_session.execute(delete(BackgroundJob))
    db_session.commit()


@pytest.fixture
def jobs_admin(db_session):
    suffix = uuid4().hex[:8]
    user = User(
        user_id=str(uuid4()), name=f'jobs-admin-{suffix}',
        email=f'jobs-admin-{suffix}@example.test', role='admin',
        is_email_verified=True,
    )
    user.set_password('test-password')
    db_session.add(user)
    db_session.commit()
    return user


def login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_job_is_claimed_and_completed(app, db_session):
    with app.app_context():
        job = enqueue('system.noop', {'value': 42})
        claimed = claim_next('test-worker')
        assert claimed.id == job.id
        assert claimed.status == 'running'
        assert claimed.attempts == 1

        execute(claimed, 'test-worker')
        completed = db.session.get(BackgroundJob, job.id)
        assert completed.status == 'completed'
        assert completed.progress == 100
        assert completed.result == {'echo': {'value': 42}}
        assert completed.locked_by is None


def test_stale_job_is_requeued(app, db_session):
    with app.app_context():
        job = BackgroundJob(
            task_name='system.noop', status='running', attempts=1,
            max_attempts=3, locked_by='dead-worker',
            heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.session.add(job)
        db.session.commit()

        assert recover_stale_jobs(stale_after_seconds=60) == 1
        db.session.refresh(job)
        assert job.status == 'queued'
        assert job.locked_by is None
        assert job.progress_message == 'Recovered after worker interruption'


def test_admin_can_list_cancel_and_retry_jobs(client, app, db_session, jobs_admin):
    with app.app_context():
        job = enqueue('system.noop', {'source': 'test'}, created_by_id=jobs_admin.id)
        job_id = job.id
    login(client, jobs_admin)

    response = client.get('/api/background-jobs')
    assert response.status_code == 200
    assert response.get_json()['jobs'][0]['id'] == job_id

    response = client.post(f'/api/background-jobs/{job_id}/cancel')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'cancelled'

    response = client.post(f'/api/background-jobs/{job_id}/retry')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'queued'
    assert response.get_json()['attempts'] == 0


def test_anonymous_user_cannot_inspect_jobs(client, app):
    with app.app_context():
        job_id = enqueue('system.noop').id
    response = client.get(f'/api/background-jobs/{job_id}')
    assert response.status_code == 302


def test_library_scan_task_runs_existing_scanner(app, db_session, tmp_path):
    from sharewarez.platform import LibraryPlatform
    from sharewarez.models import Library

    with app.app_context():
        library = Library(name=f'queue-library-{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
        db.session.add(library)
        db.session.commit()
        job = enqueue('library.scan', {
            'library_uuid': library.uuid,
            'folder_path': str(tmp_path),
            'scan_mode': 'folders',
            'remove_missing': True,
        })
        claimed = claim_next('scan-worker')

        with patch('sharewarez.utilities.scan_and_add_games') as scanner:
            execute(claimed, 'scan-worker')

        scanner.assert_called_once_with(
            str(tmp_path), scan_mode='folders',
            library_uuid=library.uuid, remove_missing=True,
            download_missing_images=False, force_updates_extras_scan=False,
            fetch_hltb=False, force_hltb_refetch=False,
        )
        completed = db.session.get(BackgroundJob, job.id)
        assert completed.status == 'completed'
        assert completed.result['library_uuid'] == library.uuid
        assert completed.result['skipped'] is False


def test_unchanged_library_scan_is_skipped(app, db_session, tmp_path):
    from sharewarez.platform import LibraryPlatform
    from sharewarez.models import Library

    (tmp_path / 'game.iso').write_bytes(b'game-data')
    with app.app_context():
        library = Library(name=f'incremental-{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
        db.session.add(library)
        db.session.commit()
        payload = {'library_uuid': library.uuid, 'folder_path': str(tmp_path), 'scan_mode': 'files'}

        with patch('sharewarez.utilities.scan_and_add_games') as scanner:
            first = enqueue('library.scan', payload)
            execute(claim_next('scan-worker'), 'scan-worker')
            second = enqueue('library.scan', payload)
            execute(claim_next('scan-worker'), 'scan-worker')

        assert scanner.call_count == 1
        assert db.session.get(BackgroundJob, first.id).result['skipped'] is False
        assert db.session.get(BackgroundJob, second.id).result['skipped'] is True


def test_due_schedule_dispatches_scan_job(app, db_session, tmp_path):
    from sharewarez.platform import LibraryPlatform
    from sharewarez.models import Library
    from sharewarez.utils.incremental_scanning import dispatch_due_schedules

    now = datetime.now(timezone.utc)
    with app.app_context():
        library = Library(name=f'scheduled-{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
        db.session.add(library)
        db.session.flush()
        schedule = LibraryScanSchedule(
            library_uuid=library.uuid, folder_path=str(tmp_path), scan_mode='folders',
            interval_minutes=60, next_run=now - timedelta(minutes=1),
        )
        db.session.add(schedule)
        db.session.commit()

        jobs = dispatch_due_schedules(now)
        assert len(jobs) == 1
        assert jobs[0].task_name == 'library.scan'
        assert jobs[0].payload['library_uuid'] == library.uuid
        db.session.refresh(schedule)
        assert schedule.last_job_id == jobs[0].id
        assert schedule.next_run == now + timedelta(minutes=60)


def test_admin_can_manage_scan_schedule(client, app, db_session, jobs_admin, tmp_path):
    from sharewarez.platform import LibraryPlatform
    from sharewarez.models import Library

    with app.app_context():
        library = Library(name=f'api-schedule-{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
        db.session.add(library)
        db.session.commit()
        library_uuid = library.uuid
    app.config['DATA_FOLDER_WAREZ'] = str(tmp_path)
    login(client, jobs_admin)

    response = client.post('/api/scan-schedules', json={
        'library_uuid': library_uuid, 'folder_path': str(tmp_path),
        'scan_mode': 'folders', 'interval_minutes': 60,
    })
    assert response.status_code == 201
    schedule_id = response.get_json()['id']

    response = client.get('/api/scan-schedules')
    assert response.status_code == 200
    assert any(item['id'] == schedule_id for item in response.get_json()['schedules'])

    response = client.patch(f'/api/scan-schedules/{schedule_id}', json={'is_enabled': False})
    assert response.status_code == 200
    assert response.get_json()['is_enabled'] is False

    assert client.delete(f'/api/scan-schedules/{schedule_id}').status_code == 204
