"""Dedicated persistent background-job worker process."""

import os
import signal
import time

from sharewarez import create_app, db
from sharewarez.utils.background_jobs import claim_next, execute, recover_stale_jobs, worker_identity


def run_worker():
    app = create_app()
    worker_id = worker_identity()
    poll_seconds = max(0.2, float(os.getenv('JOB_POLL_SECONDS', '1')))
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with app.app_context():
        recovered = recover_stale_jobs()
        app.logger.info("Background worker %s started; recovered %s job(s)", worker_id, recovered)
        while not stopping:
            job = claim_next(worker_id)
            if job is None:
                db.session.remove()
                time.sleep(poll_seconds)
                continue
            execute(job, worker_id)
            db.session.remove()
        app.logger.info("Background worker %s stopped", worker_id)


if __name__ == '__main__':
    run_worker()
