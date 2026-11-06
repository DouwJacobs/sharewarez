from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import AllowedFileType, BackgroundJob, Game, GlobalSettings, Library, LibraryScanState, ScanJob, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.background_jobs import enqueue, claim_next, execute


@pytest.fixture
def scan_run(app, db_session, tmp_path):
    app.config.update(BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path), DATA_FOLDER_WAREZ=str(tmp_path))
    library = Library(name=f'Lifecycle {uuid4().hex}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.scan_thread_count = 1
    settings.enable_game_updates = settings.enable_game_extras = False
    if not db_session.query(AllowedFileType).filter_by(value='iso').first():
        db_session.add(AllowedFileType(value='iso'))
    db_session.commit()
    return library, tmp_path


def run_scan(library, root, **options):
    queue = f'scan-{uuid4().hex}'
    job = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root), 'scan_mode': 'folders', **options}, queue=queue, max_attempts=1)
    execute(claim_next('lifecycle-worker', queue=queue), 'lifecycle-worker')
    db.session.refresh(job)
    return job


def test_scanner_early_failure_never_reports_success_or_saves_fingerprint(scan_run, db_session):
    library, root = scan_run
    db_session.query(AllowedFileType).delete()
    db_session.commit()
    (root / 'Game').mkdir()
    job = run_scan(library, root)
    assert job.status == 'failed'
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0


def test_partial_failure_is_committed_before_queue_failure(scan_run, db_session):
    library, root = scan_run
    (root / 'A').mkdir()
    (root / 'B').mkdir()
    observed = []
    def process(name, path, detail_id, *args, **kwargs):
        detail = db_session.get(ScanJob, detail_id)
        owner = db_session.get(BackgroundJob, detail.background_job_id)
        observed.append(owner.payload['scan_job_id'])
        if name == 'B':
            raise OSError('fixture persistence failure')
        return True
    with patch('sharewarez.utilities.process_game_with_fallback', side_effect=process):
        job = run_scan(library, root)
    detail = db_session.get(ScanJob, job.payload['scan_job_id'])
    assert job.status == 'failed'
    assert detail.status == 'Failed' and detail.outcome == 'partial'
    assert (detail.folders_success, detail.folders_failed) == (1, 1)
    assert observed == [detail.id, detail.id]
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0


def test_retry_preserves_failed_attempt_and_creates_new_detail(scan_run, db_session):
    from sharewarez.utils.background_jobs import retry_job
    library, root = scan_run
    (root / 'Game').mkdir()
    with patch('sharewarez.utilities.process_game_with_fallback', side_effect=OSError('failure')):
        job = run_scan(library, root)
    old_id = job.payload['scan_job_id']
    retry_job(job)
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=True):
        execute(claim_next('lifecycle-worker', queue=job.queue), 'lifecycle-worker')
    db_session.refresh(job)
    assert job.status == 'completed' and job.payload['scan_job_id'] != old_id
    assert db_session.get(ScanJob, old_id).outcome == 'failed'
    assert db_session.get(ScanJob, job.payload['scan_job_id']).outcome == 'completed'
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 1


def test_recorded_unmatched_is_processed_but_unrecorded_false_is_failure(scan_run, db_session):
    from sharewarez.models import UnmatchedFolder
    library, root = scan_run
    (root / 'Game').mkdir()
    def unmatched(name, path, scan_id, library_uuid, **kwargs):
        db.session.add(UnmatchedFolder(folder_path=path, scan_job_id=scan_id, library_uuid=library_uuid, status='Unmatched', content_type='Games'))
        db.session.commit()
        return False
    with patch('sharewarez.utilities.process_game_with_fallback', side_effect=unmatched):
        job = run_scan(library, root)
    detail = db_session.get(ScanJob, job.payload['scan_job_id'])
    assert job.status == 'completed' and detail.folders_unmatched == 1 and detail.folders_failed == 0
    db_session.query(UnmatchedFolder).filter_by(library_uuid=library.uuid).delete()
    db_session.commit()
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=False):
        failed = run_scan(library, root, force_scan=True)
    assert failed.status == 'failed'


@pytest.mark.parametrize('workers', [1, 2])
def test_cancel_stops_new_units_and_preserves_terminal_detail(scan_run, db_session, workers):
    from sharewarez.utils.background_jobs import cancel_job
    library, root = scan_run
    for index in range(8):
        (root / f'Game {index}').mkdir()
    settings = db_session.query(GlobalSettings).first()
    settings.scan_thread_count = workers
    db_session.commit()
    calls = []
    def cancel(name, path, scan_id, *args, **kwargs):
        calls.append(path)
        detail = db.session.get(ScanJob, scan_id)
        cancel_job(db.session.get(BackgroundJob, detail.background_job_id))
        return True
    with patch('sharewarez.utilities.process_game_with_fallback', side_effect=cancel):
        job = run_scan(library, root)
    assert job.status == 'cancelled'
    assert len(calls) <= workers
    detail = db_session.get(ScanJob, job.payload['scan_job_id'])
    assert detail.outcome == 'cancelled' and detail.current_processing is None
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0


def test_skip_is_durable_but_explicit_scan_forces_execution(scan_run, db_session):
    library, root = scan_run
    (root / 'Game').mkdir()
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=True) as process:
        first = run_scan(library, root)
        second = run_scan(library, root)
        forced = run_scan(library, root, force_scan=True)
    assert first.status == second.status == forced.status == 'completed'
    assert second.result['skipped'] and db_session.get(ScanJob, second.payload['scan_job_id']).outcome == 'skipped'
    assert process.call_count == 2


def test_restart_posts_share_one_replacement_and_keep_history(scan_run, app, db_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sharewarez.utils.scan_lifecycle import restart_scan
    library, root = scan_run
    detail = ScanJob(library_uuid=library.uuid, scan_folder=str(root), status='Failed', outcome='partial', folders_success=2,
                     setting_remove=True, scan_options={'fetch_hltb': True})
    db_session.add(detail)
    db_session.commit()
    detail_id = detail.id
    barrier = Barrier(2)
    def restart():
        with app.app_context():
            barrier.wait()
            return restart_scan(detail_id).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: restart(), range(2)))
    assert ids[0] == ids[1]
    job = db_session.get(BackgroundJob, ids[0])
    assert job.payload['fetch_hltb'] and job.payload['remove_missing'] and job.payload['force_scan']
    assert not job.payload['force_hltb_refetch']
    db_session.refresh(detail)
    assert detail.status == 'Failed' and detail.folders_success == 2


def test_history_deletion_protects_active_and_referenced_details(scan_run, db_session):
    from sharewarez.models import UnmatchedFolder
    from sharewarez.utils.scan_lifecycle import delete_scan_history
    library, root = scan_run
    queued = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root)})
    rows = [ScanJob(library_uuid=library.uuid, status=status) for status in ('Running', 'Stopping', 'Failed', 'Failed', 'Completed')]
    rows[2].background_job_id = queued.id
    db_session.add_all(rows)
    db_session.flush()
    db_session.add(UnmatchedFolder(library_uuid=library.uuid, scan_job_id=rows[3].id, folder_path=str(root / 'Unmatched'), status='Unmatched', content_type='Games'))
    db_session.commit()
    ids = [row.id for row in rows]
    assert delete_scan_history([ids[0]]) == (0, 1)
    assert delete_scan_history(ids) == (1, 4)


def test_web_restart_does_not_recover_worker_scans(scan_run, db_session):
    from sharewarez.init_manager import InitializationManager
    from sharewarez.utils.background_jobs import recover_stale_jobs
    library, root = scan_run
    job = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root)}, queue=f'test-{uuid4().hex}')
    claimed = claim_next('previous-worker', queue=job.queue)
    row = ScanJob(library_uuid=library.uuid, status='Running', background_job_id=claimed.id, folders_success=3)
    db_session.add(row)
    db_session.commit()
    InitializationManager()._cleanup_orphaned_scan_jobs(db_session)
    db_session.commit()
    db_session.refresh(row)
    assert row.status == 'Running'
    recover_stale_jobs(stale_after_seconds=0)
    db_session.refresh(row)
    db_session.refresh(job)
    assert row.outcome == 'interrupted' and row.folders_success == 3
    assert job.status == 'queued'


def test_finalization_store_error_cannot_complete_or_save_fingerprint(scan_run, db_session):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError
    library, root = scan_run
    (root / 'Game').mkdir()
    injected = []
    def fail_once(session, *_args):
        if not injected and any(isinstance(row, ScanJob) and row.outcome == 'completed' for row in session.dirty):
            injected.append(True)
            raise SQLAlchemyError('injected finalization failure')
    session_class = type(db_session())
    event.listen(session_class, 'before_flush', fail_once)
    try:
        with patch('sharewarez.utilities.process_game_with_fallback', return_value=True):
            job = run_scan(library, root)
    finally:
        event.remove(session_class, 'before_flush', fail_once)
    assert injected and job.status == 'failed'
    assert db_session.get(ScanJob, job.payload['scan_job_id']).outcome == 'partial'
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0


def test_cancellation_at_success_boundary_does_not_save_state(scan_run, db_session):
    from sharewarez.utils.background_jobs import cancel_job
    from sharewarez.utils.scan_lifecycle import finish_scan
    library, root = scan_run
    def finish_then_cancel(*args, **kwargs):
        detail = kwargs['existing_job']
        result = finish_scan(detail.id, 'completed')
        cancel_job(db.session.get(BackgroundJob, detail.background_job_id))
        return result
    with patch('sharewarez.utilities.scan_and_add_games', side_effect=finish_then_cancel):
        job = run_scan(library, root)
    assert job.status == 'cancelled'
    assert db_session.get(ScanJob, job.payload['scan_job_id']).outcome == 'cancelled'
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0


def test_both_cancel_routes_address_same_durable_owner(scan_run, db_session, client):
    from sharewarez.utils.scan_lifecycle import create_scan_detail
    library, root = scan_run
    admin = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='admin', password_hash='unused')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    queue = f'cancel-{uuid4().hex}'
    job = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root)}, queue=queue)
    claim_next('owner', queue=queue)
    detail = create_scan_detail(str(root), 'folders', library.uuid, {}, job)
    for endpoint in (f'/cancel_scan_job/{detail.id}', f'/admin/background-jobs/{job.id}/cancel'):
        assert client.post(endpoint).status_code == 302
        db_session.refresh(job)
        db_session.refresh(detail)
        assert job.cancel_requested and detail.status == 'Stopping' and not detail.is_enabled
    queued = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root)})
    assert client.post(f'/cancel_scan_job/{queued.id}').status_code == 302
    db_session.refresh(queued)
    assert queued.status == 'cancelled'
    assert client.post(f'/delete_scan_job/{detail.id}').status_code == 302
    assert db_session.get(ScanJob, detail.id) is not None


def test_scan_status_exposes_partial_and_queued_work(scan_run, db_session, client):
    library, root = scan_run
    admin = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='admin', password_hash='unused')
    detail = ScanJob(library_uuid=library.uuid, scan_folder=str(root), status='Failed', outcome='partial', folders_success=1, folders_failed=1, folders_unmatched=1, total_folders=3)
    db_session.add_all([admin, detail])
    db_session.commit()
    queued = enqueue('library.scan', {'library_uuid': library.uuid, 'folder_path': str(root)})
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    response = client.get('/api/scan_jobs_status')
    rows = {row['id']: row for row in response.json}
    assert rows[detail.id]['display_status'] == 'Partial'
    assert rows[detail.id]['progress_percentage'] == 100
    assert rows[queued.id]['display_status'] == 'Queued' and rows[queued.id]['cancel_url']
    assert rows[queued.id]['job_url'] and not rows[queued.id]['can_restart']


def test_fingerprint_store_failure_is_a_partial_failed_attempt(scan_run, db_session):
    from sqlalchemy.exc import SQLAlchemyError
    library, root = scan_run
    (root / 'Game').mkdir()
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=True), patch('sharewarez.utils.incremental_scanning.save_scan_state', side_effect=SQLAlchemyError('state store failed')):
        job = run_scan(library, root)
    assert job.status == 'failed'
    detail = db_session.get(ScanJob, job.payload['scan_job_id'])
    assert detail.status == 'Failed' and detail.outcome == 'partial' and detail.folders_success == 1
    assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0


def test_cancelling_queued_retry_preserves_previous_terminal_attempt(scan_run, db_session):
    from sharewarez.utils.background_jobs import retry_job, cancel_job
    library, root = scan_run
    (root / 'A').mkdir()
    (root / 'B').mkdir()
    def process(name, *args, **kwargs):
        if name == 'B':
            raise OSError('failure after A')
        return True
    with patch('sharewarez.utilities.process_game_with_fallback', side_effect=process):
        job = run_scan(library, root)
    detail_id = job.payload['scan_job_id']
    assert db_session.get(ScanJob, detail_id).outcome == 'partial'
    retry_job(job)
    cancel_job(job)
    assert db_session.get(ScanJob, detail_id, populate_existing=True).outcome == 'partial'


def test_supplemental_failure_after_match_is_partial(scan_run, db_session):
    library, root = scan_run
    (root / 'Game').mkdir()
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=True), patch('sharewarez.utilities._scan_enabled_supplemental_content', side_effect=OSError('supplemental failure')):
        job = run_scan(library, root)
    assert job.status == 'failed'
    assert db_session.get(ScanJob, job.payload['scan_job_id']).outcome == 'partial'


def test_default_hltb_option_does_not_prevent_unchanged_scheduled_skip(scan_run, db_session):
    library, root = scan_run
    (root / 'Game').mkdir()
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=True) as provider:
        first = run_scan(library, root, fetch_hltb=True)
        second = run_scan(library, root, fetch_hltb=True)
    assert first.status == second.status == 'completed'
    assert second.result['skipped'] and provider.call_count == 1


def test_cancellation_during_cleanup_stops_further_removals(scan_run, db_session):
    from sharewarez.utils.background_jobs import cancel_job
    library, root = scan_run
    (root / 'Present').mkdir()
    db_session.add_all([Game(name='Present', library_uuid=library.uuid, full_disk_path=str(root / 'Present')),
                        Game(name='Missing A', library_uuid=library.uuid, full_disk_path=str(root / 'Missing A')),
                        Game(name='Missing B', library_uuid=library.uuid, full_disk_path=str(root / 'Missing B'))])
    db_session.commit()
    def remove(_uuid):
        detail = db_session.query(ScanJob).filter_by(library_uuid=library.uuid).one()
        cancel_job(db_session.get(BackgroundJob, detail.background_job_id))
        return True
    with patch('sharewarez.utilities.remove_from_lib', side_effect=remove) as removal:
        job = run_scan(library, root, remove_missing=True)
    detail = db_session.get(ScanJob, job.payload['scan_job_id'])
    assert removal.call_count == 1 and detail.removed_count == 1
    assert job.status == 'cancelled' and detail.outcome == 'cancelled'
    assert 'No further removals performed' in detail.error_message


def test_invalid_legacy_queue_options_have_a_failed_detail(scan_run, db_session):
    library, root = scan_run
    with patch('sharewarez.utils.incremental_scanning.filesystem_fingerprint') as fingerprint:
        job = run_scan(library, root, remove_missing='false')
    assert job.status == 'failed'
    detail = db_session.get(ScanJob, job.payload['scan_job_id'])
    assert detail.outcome == 'failed' and not detail.setting_remove
    fingerprint.assert_not_called()


def test_scheduled_hltb_choices_survive_global_disable_before_execution(scan_run, db_session):
    from sharewarez.models import LibraryScanSchedule
    from sharewarez.utils.incremental_scanning import enqueue_scheduled_scan
    library, root = scan_run
    (root / 'Known').mkdir(); (root / 'New').mkdir()
    db_session.add(Game(name='Known', library_uuid=library.uuid, full_disk_path=str(root / 'Known')))
    settings = db_session.query(GlobalSettings).first()
    settings.enable_hltb_integration = True
    schedule = LibraryScanSchedule(library_uuid=library.uuid, folder_path=str(root), scan_mode='folders', interval_minutes=1440,
        options={'fetch_hltb':True,'force_hltb_refetch':True}, next_run=datetime.now(timezone.utc))
    db_session.add(schedule); db_session.commit()
    job = enqueue_scheduled_scan(schedule, force=True)
    job.queue = f'policy-{uuid4().hex}'
    settings.enable_hltb_integration = False
    db_session.commit()
    with patch('sharewarez.utilities.process_game_with_fallback',return_value=True) as provider, patch('sharewarez.utils.hltb.update_game_hltb_sync') as force_lookup:
        execute(claim_next('policy-worker', queue=job.queue), 'policy-worker')
    db_session.refresh(job); db_session.refresh(schedule)
    assert job.status == 'completed'
    assert provider.call_count == 1 and provider.call_args.kwargs['fetch_hltb'] is False
    force_lookup.assert_not_called()
    assert schedule.options == {'fetch_hltb':True,'force_hltb_refetch':True}
    settings.enable_hltb_integration = True
    db_session.commit()
    again = enqueue_scheduled_scan(schedule, force=True)
    assert again.payload['fetch_hltb'] and again.payload['force_hltb_refetch']
    again.queue = f'policy-{uuid4().hex}'
    db_session.commit()
    with patch('sharewarez.utilities.process_game_with_fallback',return_value=True) as provider, patch('sharewarez.utils.hltb.update_game_hltb_sync') as force_lookup:
        execute(claim_next('enabled-policy-worker', queue=again.queue), 'enabled-policy-worker')
    db_session.refresh(again)
    assert again.status == 'completed'
    assert provider.call_count == 1 and provider.call_args.kwargs['fetch_hltb'] is True
    force_lookup.assert_called_once()
