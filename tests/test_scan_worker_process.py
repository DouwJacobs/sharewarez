"""Exercise real worker shutdown/restart independently of web initialization."""
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from sharewarez import db
from sharewarez.models import AllowedFileType, BackgroundJob, Game, GlobalSettings, Library, LibraryScanState, ScanJob
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.background_jobs import enqueue, retry_job


WORKER = '''
import sys, time
from pathlib import Path
from sharewarez import create_app, job_worker, utilities
app = create_app()
app.config.update(BASE_FOLDER_POSIX=sys.argv[1], BASE_FOLDER_WINDOWS=sys.argv[1], DATA_FOLDER_WAREZ=sys.argv[1], DOWNLOAD_CACHE_DIR=sys.argv[2])
def unit(*args, **kwargs):
    Path(sys.argv[3]).touch()
    time.sleep(float(sys.argv[4]))
utilities._scan_enabled_supplemental_content = unit
job_worker.create_app = lambda: app
job_worker.run_worker()
'''


def test_worker_shutdown_retry_and_crash_recovery(app, db_session, tmp_path):
    root = tmp_path / 'storage'
    root.mkdir()
    library = Library(name=f'Process {uuid4().hex}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    for index in range(12):
        path = root / f'Game {index:02}'
        path.mkdir()
        db_session.add(Game(name=path.name, full_disk_path=str(path), library_uuid=library.uuid))
    db_session.add(AllowedFileType(value='isotest'))
    settings = GlobalSettings(scan_thread_count=1, enable_game_updates=False, enable_game_extras=False)
    db_session.add(settings)
    db_session.commit()
    payload = {'library_uuid': library.uuid, 'folder_path': str(root), 'scan_mode': 'folders', 'force_scan': True}
    job = enqueue('library.scan', payload)
    marker = tmp_path / 'unit-started'
    processes = []
    log_path = tmp_path / 'worker.log'
    env = dict(os.environ, DATABASE_URL=app.config['SQLALCHEMY_DATABASE_URI'], TEST_DATABASE_URL=app.config['SQLALCHEMY_DATABASE_URI'], JOB_POLL_SECONDS='0.2', GAMELIBRARY_INITIALIZATION_COMPLETE='true')

    def wait_for(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            db_session.expire_all()
            if predicate():
                return
            time.sleep(0.1)
        raise AssertionError(log_path.read_text()[-2500:])

    def start(delay):
        with log_path.open('a') as log:
            process = subprocess.Popen([sys.executable, '-u', '-c', WORKER, str(root), str(tmp_path / 'cache'), str(marker), str(delay)], cwd=Path(__file__).resolve().parents[1], env=env, stdout=log, stderr=log)
        processes.append(process)
        return process

    try:
        first = start(1)
        wait_for(marker.exists)
        db_session.refresh(job)
        first_id = job.payload['scan_job_id']
        # A different process runs the same startup cleanup as the web process.
        subprocess.run([sys.executable, '-c', 'from sharewarez import create_app, db; from sharewarez.init_manager import InitializationManager; app=create_app(); app.app_context().push(); InitializationManager()._cleanup_orphaned_scan_jobs(db.session); db.session.commit()'], cwd=Path(__file__).resolve().parents[1], env=env, check=True, capture_output=True, timeout=30)
        db_session.expire_all()
        assert db_session.get(ScanJob, first_id).status == 'Running'
        first.terminate()
        first.wait(timeout=20)
        db_session.refresh(job)
        assert job.status == 'cancelled'
        assert db_session.get(ScanJob, first_id, populate_existing=True).outcome == 'cancelled'
        assert db_session.query(LibraryScanState).filter_by(library_uuid=library.uuid).count() == 0

        retry_job(job)
        second = start(0)
        wait_for(lambda: db_session.get(BackgroundJob, job.id).status == 'completed')
        second.terminate()
        second.wait(timeout=10)
        db_session.refresh(job)
        assert job.payload['scan_job_id'] != first_id
        assert db_session.get(ScanJob, first_id, populate_existing=True).outcome == 'cancelled'

        marker.unlink()
        crashed = enqueue('library.scan', payload)
        third = start(1)
        wait_for(marker.exists)
        db_session.refresh(crashed)
        interrupted_id = crashed.payload['scan_job_id']
        third.kill()
        third.wait(timeout=10)
        fourth = start(0)
        wait_for(lambda: db_session.get(BackgroundJob, crashed.id).status == 'completed')
        fourth.terminate()
        fourth.wait(timeout=10)
        db_session.refresh(crashed)
        assert crashed.payload['scan_job_id'] != interrupted_id
        assert db_session.get(ScanJob, interrupted_id, populate_existing=True).outcome == 'interrupted'
        assert crashed.attempts == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
