"""Dedicated persistent background-job worker process."""

import os
import signal
import time
import threading

from sqlalchemy import select

from sharewarez import create_app, db
from sharewarez.models import GlobalSettings
from sharewarez.utils.background_jobs import claim_next, execute, recover_stale_jobs, worker_identity


def maintain_downloads(app, stopping, interval=15):
    """Independent maintenance cannot be delayed by a long scan or cache build."""
    from sharewarez.utils.download_limits import expire_download_requests, mark_stale_transfers
    while not stopping.is_set():
        with app.app_context():
            try:
                mark_stale_transfers()
                expire_download_requests()
            except Exception:
                db.session.rollback()
                app.logger.exception("Download transfer maintenance failed")
            finally:
                db.session.remove()
        stopping.wait(interval)


def run_worker():
    app = create_app()
    worker_id = worker_identity()
    poll_seconds = max(0.2, float(os.getenv('JOB_POLL_SECONDS', '1')))
    stopping = threading.Event()
    last_schedule_check = 0.0

    def stop(*_args):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with app.app_context():
        # This deployment owns exactly one job-worker process. Any job still marked
        # running at process startup belonged to the previous process and is recoverable
        # immediately, including a cancellation requested just before restart.
        recovered = recover_stale_jobs(stale_after_seconds=0)
        from sharewarez.utils.download_cache import reconcile_cache
        reconciliation = reconcile_cache()
        app.logger.info("Background worker %s started; recovered %s job(s)", worker_id, recovered)
        if reconciliation['partials_removed'] or reconciliation['invalidated']:
            app.logger.warning('Download cache reconciled at startup: %s', reconciliation)
        settings = db.session.execute(select(GlobalSettings)).scalars().first()
        configured = int((settings.settings or {}).get('archiveCacheBuildConcurrency', 1)) if settings else 1
        archive_workers = max(1, min(configured, 4))

        def consume_archives(index):
            archive_worker_id = f'{worker_id}:archive:{index}'
            last_cleanup = 0.0
            with app.app_context():
                while not stopping.is_set():
                    monotonic_now = time.monotonic()
                    if index == 0 and monotonic_now - last_cleanup >= 900:
                        try:
                            from sharewarez.utils.download_cache import cleanup_cache
                            cleanup_cache()
                        except Exception:
                            app.logger.exception('Automatic download-cache cleanup failed')
                            db.session.rollback()
                        last_cleanup = monotonic_now
                    archive_job = claim_next(archive_worker_id, queue='archive')
                    if archive_job is None:
                        db.session.remove()
                        stopping.wait(poll_seconds)
                        continue
                    execute(archive_job, archive_worker_id)
                    db.session.remove()

        archive_threads = [
            threading.Thread(target=consume_archives, args=(index,), daemon=True)
            for index in range(archive_workers)
        ]
        for thread in archive_threads:
            thread.start()
        maintenance_thread = threading.Thread(
            target=maintain_downloads, args=(app, stopping), name='download-maintenance', daemon=True,
        )
        maintenance_thread.start()

        while not stopping.is_set():
            monotonic_now = time.monotonic()
            if monotonic_now - last_schedule_check >= 30:
                from sharewarez.utils.incremental_scanning import dispatch_due_schedules
                dispatched = dispatch_due_schedules()
                if dispatched:
                    app.logger.info("Dispatched %s scheduled scan(s)", len(dispatched))
                last_schedule_check = monotonic_now
            job = claim_next(worker_id, queue='default')
            if job is None:
                db.session.remove()
                stopping.wait(poll_seconds)
                continue
            execute(job, worker_id)
            db.session.remove()
        for thread in archive_threads:
            thread.join(timeout=5)
        maintenance_thread.join(timeout=5)
        app.logger.info("Background worker %s stopped", worker_id)


if __name__ == '__main__':
    run_worker()
