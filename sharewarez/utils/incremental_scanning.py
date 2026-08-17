"""Filesystem fingerprints and recurring scan dispatch."""

from datetime import datetime, timedelta, timezone
import hashlib
import os

from sqlalchemy import select

from sharewarez import db
from sharewarez.models import LibraryScanSchedule, LibraryScanState


SCHEDULE_INTERVALS = {
    60: 'Every hour', 360: 'Every 6 hours', 720: 'Every 12 hours',
    1440: 'Daily', 4320: 'Every 3 days', 10080: 'Weekly',
}


def filesystem_fingerprint(folder_path, context=None):
    """Hash relative paths and stable stat metadata without reading file contents."""
    digest = hashlib.sha256()
    entry_count = 0
    total_size = 0
    root_path = os.path.realpath(folder_path)
    if not os.path.isdir(root_path):
        raise FileNotFoundError(f"Scan folder is unavailable: {folder_path}")

    for current_root, directories, files in os.walk(root_path):
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            path = os.path.join(current_root, name)
            relative = os.path.relpath(path, root_path).replace(os.sep, '/')
            try:
                stat = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            is_directory = os.path.isdir(path)
            size = 0 if is_directory else stat.st_size
            digest.update(f"{'d' if is_directory else 'f'}\0{relative}\0{size}\0{stat.st_mtime_ns}\n".encode())
            entry_count += 1
            total_size += size
            if context and entry_count % 250 == 0:
                context.heartbeat(message=f"Indexed {entry_count:,} filesystem entries")
    return digest.hexdigest(), entry_count, total_size


def get_scan_state(library_uuid, folder_path, scan_mode):
    return db.session.execute(
        select(LibraryScanState).where(
            LibraryScanState.library_uuid == library_uuid,
            LibraryScanState.folder_path == os.path.realpath(folder_path),
            LibraryScanState.scan_mode == scan_mode,
        )
    ).scalar_one_or_none()


def has_changed(library_uuid, folder_path, scan_mode, fingerprint):
    state = get_scan_state(library_uuid, folder_path, scan_mode)
    return state is None or state.fingerprint != fingerprint


def save_scan_state(library_uuid, folder_path, scan_mode, fingerprint, entry_count, total_size):
    normalized = os.path.realpath(folder_path)
    state = get_scan_state(library_uuid, normalized, scan_mode)
    if state is None:
        state = LibraryScanState(
            library_uuid=library_uuid, folder_path=normalized, scan_mode=scan_mode,
            fingerprint=fingerprint,
        )
        db.session.add(state)
    state.fingerprint = fingerprint
    state.entry_count = entry_count
    state.total_size = total_size
    state.scanned_at = datetime.now(timezone.utc)
    db.session.commit()
    return state


def dispatch_due_schedules(now=None):
    """Atomically enqueue all schedules that are currently due."""
    now = now or datetime.now(timezone.utc)
    schedules = db.session.execute(
        select(LibraryScanSchedule)
        .where(LibraryScanSchedule.is_enabled.is_(True), LibraryScanSchedule.next_run <= now)
        .order_by(LibraryScanSchedule.next_run.asc())
        .with_for_update(skip_locked=True)
    ).scalars().all()
    dispatched = []
    for schedule in schedules:
        job = enqueue_scheduled_scan(schedule)
        schedule.last_run = now
        schedule.last_job_id = job.id
        schedule.next_run = now + timedelta(minutes=schedule.interval_minutes)
        db.session.commit()
        dispatched.append(job)
    return dispatched


def enqueue_scheduled_scan(schedule, *, created_by_id=None):
    """Queue one execution without changing the schedule's recurring cadence."""
    from sharewarez.utils.background_jobs import enqueue

    payload = {
        'library_uuid': schedule.library_uuid,
        'folder_path': schedule.folder_path,
        'scan_mode': schedule.scan_mode,
        'schedule_id': schedule.id,
        **dict(schedule.options or {}),
    }
    return enqueue(
        'library.scan', payload, max_attempts=3, created_by_id=created_by_id,
    )
