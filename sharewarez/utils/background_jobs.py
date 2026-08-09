"""Persistent background-job queue primitives."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import socket
from typing import Callable

from flask import current_app
from sqlalchemy import or_, select

from sharewarez import db
from sharewarez.models import BackgroundJob


JobHandler = Callable[["JobContext", dict], dict | None]
_handlers: dict[str, JobHandler] = {}


class JobCancelled(Exception):
    """Raised cooperatively when cancellation has been requested."""


def register_task(name: str):
    def decorator(handler: JobHandler):
        if name in _handlers:
            raise RuntimeError(f"Background task already registered: {name}")
        _handlers[name] = handler
        return handler
    return decorator


def enqueue(task_name, payload=None, *, queue='default', max_attempts=3, created_by_id=None):
    if task_name not in _handlers:
        raise ValueError(f"Unknown background task: {task_name}")
    if not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    job = BackgroundJob(
        task_name=task_name,
        payload=payload or {},
        queue=queue,
        max_attempts=max_attempts,
        created_by_id=created_by_id,
    )
    db.session.add(job)
    db.session.commit()
    return job


def claim_next(worker_id: str, queue='default'):
    """Atomically claim one runnable job using PostgreSQL row locking."""
    now = datetime.now(timezone.utc)
    job = db.session.execute(
        select(BackgroundJob)
        .where(
            BackgroundJob.queue == queue,
            BackgroundJob.status == 'queued',
            BackgroundJob.available_at <= now,
        )
        .order_by(BackgroundJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        db.session.rollback()
        return None
    job.status = 'running'
    job.attempts += 1
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.locked_by = worker_id
    job.error_message = None
    db.session.commit()
    return job


@dataclass
class JobContext:
    job_id: str
    worker_id: str

    def _job(self):
        job = db.session.get(BackgroundJob, self.job_id)
        if job is None or job.locked_by != self.worker_id:
            raise JobCancelled("Job ownership was lost")
        return job

    def heartbeat(self, progress=None, message=None):
        job = self._job()
        if job.cancel_requested:
            raise JobCancelled("Cancellation requested")
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if message is not None:
            job.progress_message = str(message)[:255]
        job.heartbeat_at = datetime.now(timezone.utc)
        db.session.commit()

    def check_cancelled(self):
        job = self._job()
        if job.cancel_requested:
            raise JobCancelled("Cancellation requested")


def execute(job: BackgroundJob, worker_id: str):
    handler = _handlers.get(job.task_name)
    if handler is None:
        _fail_or_retry(job.id, worker_id, f"Unknown background task: {job.task_name}", retry=False)
        return
    context = JobContext(job.id, worker_id)
    try:
        result = handler(context, job.payload or {})
        current = context._job()
        current.status = 'completed'
        current.result = result or {}
        current.progress = 100
        current.completed_at = datetime.now(timezone.utc)
        current.heartbeat_at = current.completed_at
        current.locked_by = None
        db.session.commit()
    except JobCancelled as exc:
        current = db.session.get(BackgroundJob, job.id)
        if current:
            current.status = 'cancelled'
            current.error_message = str(exc)
            current.completed_at = datetime.now(timezone.utc)
            current.locked_by = None
            db.session.commit()
    except Exception as exc:
        current_app.logger.exception("Background job %s failed", job.id)
        db.session.rollback()
        _fail_or_retry(job.id, worker_id, str(exc), retry=True)


def _fail_or_retry(job_id, worker_id, message, *, retry):
    job = db.session.get(BackgroundJob, job_id)
    if job is None or job.locked_by != worker_id:
        return
    now = datetime.now(timezone.utc)
    job.error_message = message[:4000]
    job.locked_by = None
    if retry and not job.cancel_requested and job.attempts < job.max_attempts:
        job.status = 'queued'
        job.available_at = now + timedelta(seconds=min(300, 2 ** job.attempts))
        job.progress_message = f"Retry {job.attempts + 1} of {job.max_attempts} scheduled"
    else:
        job.status = 'cancelled' if job.cancel_requested else 'failed'
        job.completed_at = now
    db.session.commit()


def recover_stale_jobs(stale_after_seconds=120):
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    jobs = db.session.execute(
        select(BackgroundJob).where(
            BackgroundJob.status == 'running',
            or_(BackgroundJob.heartbeat_at.is_(None), BackgroundJob.heartbeat_at < cutoff),
        ).with_for_update(skip_locked=True)
    ).scalars().all()
    for job in jobs:
        job.locked_by = None
        if job.cancel_requested:
            job.status = 'cancelled'
            job.completed_at = datetime.now(timezone.utc)
        elif job.attempts < job.max_attempts:
            job.status = 'queued'
            job.available_at = datetime.now(timezone.utc)
            job.progress_message = 'Recovered after worker interruption'
        else:
            job.status = 'failed'
            job.error_message = 'Worker stopped before the job completed'
            job.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    return len(jobs)


def worker_identity():
    return f"{socket.gethostname()}:{id(db)}"


@register_task('system.noop')
def noop_task(context, payload):
    context.heartbeat(100, 'Completed')
    return {'echo': payload}


@register_task('library.scan')
def library_scan_task(context, payload):
    """Run the existing scanner in the persistent worker process."""
    from sharewarez.models import Library
    from sharewarez.utilities import scan_and_add_games
    from sharewarez.utils.incremental_scanning import (
        filesystem_fingerprint, has_changed, save_scan_state,
    )

    library_uuid = payload['library_uuid']
    library = db.session.get(Library, library_uuid)
    if library is None:
        raise ValueError(f"Library not found: {library_uuid}")
    scan_mode = payload.get('scan_mode', 'folders')
    context.heartbeat(1, f"Indexing {library.name}")
    fingerprint, entry_count, total_size = filesystem_fingerprint(payload['folder_path'], context)
    force_scan = any(payload.get(key) for key in (
        'force_updates_extras_scan', 'fetch_hltb', 'force_hltb_refetch',
    ))
    if not force_scan and not has_changed(
        library_uuid, payload['folder_path'], scan_mode, fingerprint,
    ):
        context.heartbeat(99, f"No filesystem changes in {library.name}")
        return {
            'library_uuid': library_uuid, 'folder_path': payload['folder_path'],
            'skipped': True, 'entry_count': entry_count, 'total_size': total_size,
        }

    context.heartbeat(10, f"Scanning changed library {library.name}")
    scan_and_add_games(
        payload['folder_path'],
        scan_mode=scan_mode,
        library_uuid=library_uuid,
        remove_missing=bool(payload.get('remove_missing')),
        download_missing_images=bool(payload.get('download_missing_images')),
        force_updates_extras_scan=bool(payload.get('force_updates_extras_scan')),
        fetch_hltb=bool(payload.get('fetch_hltb')),
        force_hltb_refetch=bool(payload.get('force_hltb_refetch')),
    )
    save_scan_state(
        library_uuid, payload['folder_path'], scan_mode,
        fingerprint, entry_count, total_size,
    )
    context.heartbeat(99, f"Finished scanning {library.name}")
    return {
        'library_uuid': library_uuid, 'folder_path': payload['folder_path'],
        'skipped': False, 'entry_count': entry_count, 'total_size': total_size,
    }
