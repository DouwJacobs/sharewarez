from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from sharewarez.models import (
    AllowedFileType, BackgroundJob, Game, Library, LibraryScanSchedule, LibraryScanState, SystemEvents, User,
)
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.background_jobs import library_scan_task, enqueue, claim_next, execute
from sharewarez.utils.incremental_scanning import dispatch_due_schedules, enqueue_scheduled_scan


@pytest.fixture
def schedule_storage(app, db_session, client, tmp_path):
    app.config.update(BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path), DATA_FOLDER_WAREZ=str(tmp_path))
    suffix = uuid4().hex
    admin = User(name=suffix, email=f'{suffix}@example.test', role='admin', password_hash='unused')
    library = Library(name=suffix, platform=LibraryPlatform.PCWIN)
    db_session.add_all([admin, library])
    if not db_session.query(AllowedFileType).filter_by(value='iso').first():
        db_session.add(AllowedFileType(value='iso'))
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    return client, library, tmp_path


@pytest.mark.parametrize('options', [None, [], True, 'yes', {'folder_path': '/outside'}, {'library_uuid': 'bad'}, {'scan_mode': 'files'}, {'remove_missing': 1}, {'fetch_hltb': 'false'}])
def test_schedule_create_and_patch_reject_unsafe_options(schedule_storage, db_session, options):
    client, library, _ = schedule_storage
    data = {'library_uuid': library.uuid, 'folder_path': '.', 'options': options}
    assert client.post('/api/scan-schedules', json=data).status_code == 400
    data['options'] = {'remove_missing': False}
    response = client.post('/api/scan-schedules', json=data)
    assert response.status_code == 201
    schedule_id = response.json['id']
    assert client.patch(f'/api/scan-schedules/{schedule_id}', json={'options': options, 'is_enabled': False}).status_code == 400
    schedule = db_session.get(LibraryScanSchedule, schedule_id)
    assert schedule.options == {'remove_missing': False}
    assert schedule.is_enabled is True


def test_schedule_relative_file_target_and_mode_validation(schedule_storage):
    client, library, root = schedule_storage
    (root / 'game.iso').write_bytes(b'game')
    data = {'library_uuid': library.uuid, 'folder_path': 'game.iso', 'scan_mode': 'folders'}
    assert client.post('/api/scan-schedules', json=data).status_code == 400
    data['scan_mode'] = 'files'
    response = client.post('/api/scan-schedules', json=data)
    assert response.status_code == 201
    assert response.json['folder_path'] == str(root / 'game.iso')
    assert client.patch(f"/api/scan-schedules/{response.json['id']}", json={'scan_mode': 'folders'}).status_code == 400
    html = client.post('/admin/scan-schedules', data={**data, 'interval_minutes': 60})
    assert html.status_code == 302


def test_dispatch_cannot_override_validated_schedule_identity(schedule_storage, db_session):
    _, library, root = schedule_storage
    schedule = LibraryScanSchedule(
        library_uuid=library.uuid, folder_path=str(root), scan_mode='folders',
        interval_minutes=60, next_run=datetime.now(timezone.utc),
        options={'folder_path': '/outside', 'library_uuid': 'other', 'scan_mode': 'files', 'remove_missing': 'false', 'fetch_hltb': True},
    )
    db_session.add(schedule)
    db_session.commit()
    job = enqueue_scheduled_scan(schedule)
    assert job.payload['folder_path'] == str(root)
    assert job.payload['library_uuid'] == library.uuid
    assert job.payload['scan_mode'] == 'folders'
    assert job.payload['fetch_hltb'] is True
    assert 'remove_missing' not in job.payload
    assert db_session.execute(select(SystemEvents).where(SystemEvents.event_text.contains(schedule.id), SystemEvents.event_level == 'warning')).scalars().first()


def test_invalid_due_target_is_reported_without_queueing(schedule_storage, db_session):
    _, library, root = schedule_storage
    now = datetime.now(timezone.utc)
    schedule = LibraryScanSchedule(library_uuid=library.uuid, folder_path=str(root / 'absent'), scan_mode='folders', interval_minutes=60, next_run=now - timedelta(minutes=1))
    db_session.add(schedule)
    db_session.commit()
    before = db_session.query(BackgroundJob).count()
    dispatch_due_schedules(now)
    assert db_session.query(BackgroundJob).count() == before
    assert schedule.last_job_id is None
    assert schedule.next_run == now + timedelta(minutes=60)


def test_worker_revalidates_retargeted_link_before_fingerprinting(schedule_storage, db_session):
    _, library, root = schedule_storage
    (root / 'safe').mkdir()
    link = root / 'alias'
    link.symlink_to(root / 'safe', target_is_directory=True)
    payload = {'library_uuid': library.uuid, 'folder_path': str(link), 'scan_mode': 'folders'}
    link.unlink()
    link.symlink_to(root.parent, target_is_directory=True)
    queue = f'safe-{uuid4().hex}'
    job = enqueue('library.scan', payload, queue=queue, max_attempts=1)
    with patch('sharewarez.utilities.scan_and_add_games') as scanner, patch('sharewarez.utils.incremental_scanning.filesystem_fingerprint') as fingerprint:
        execute(claim_next('scan-worker', queue=queue), 'scan-worker')
    db_session.refresh(job)
    assert job.status == 'failed'
    scanner.assert_not_called()
    fingerprint.assert_not_called()


def test_worker_fingerprints_only_requested_file(schedule_storage, db_session):
    _, library, root = schedule_storage
    game = root / 'game.iso'
    game.write_bytes(b'game')
    (root / 'sibling.iso').write_bytes(b'not this game')
    db_session.add(Game(name='Game', full_disk_path=str(game), library_uuid=library.uuid))
    db_session.commit()
    queue = f'file-{uuid4().hex}'
    job = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(game), 'scan_mode': 'files'}, queue=queue, max_attempts=1)
    execute(claim_next('scan-worker', queue=queue), 'scan-worker')
    db_session.refresh(job)
    assert job.status == 'completed'
    assert job.result['entry_count'] == 1 and job.result['total_size'] == 4
    state = db_session.execute(select(LibraryScanState).where(LibraryScanState.library_uuid == library.uuid)).scalar_one()
    assert state.folder_path == str(game)


def test_durable_worker_fails_unsafe_target_without_touching_files(schedule_storage, db_session):
    _, library, root = schedule_storage
    queue = f'safety-{uuid4().hex}'
    job = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root.parent), 'scan_mode': 'folders'}, queue=queue, max_attempts=1)
    with patch('sharewarez.utils.incremental_scanning.filesystem_fingerprint') as fingerprint, patch('sharewarez.utilities.scan_and_add_games') as scanner:
        execute(claim_next('safety-worker', queue=queue), 'safety-worker')
    db_session.refresh(job)
    assert job.status == 'failed'
    assert 'outside allowed scan directories' in job.error_message
    fingerprint.assert_not_called()
    scanner.assert_not_called()
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0
