"""Filesystem fingerprints and recurring scan dispatch."""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import stat

from flask import current_app

from sqlalchemy import select

from sharewarez import db
from sharewarez.models import LibraryScanSchedule, LibraryScanState, AllowedFileType, SystemEvents
from sharewarez.utils.scan_targets import legacy_scan_options, resolve_scan_target, within


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
    root_info = os.stat(root_path)
    if stat.S_ISREG(root_info.st_mode):
        digest.update(f"f\0{os.path.basename(root_path)}\0{root_info.st_size}\0{root_info.st_mtime_ns}\n".encode())
        return digest.hexdigest(), 1, root_info.st_size
    if not stat.S_ISDIR(root_info.st_mode):
        raise OSError('Scan target is not a regular file or directory')

    def walk_error(error):
        raise error

    for current_root, directories, files in os.walk(root_path, onerror=walk_error):
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            path = os.path.join(current_root, name)
            if not within(os.path.realpath(path), root_path):
                raise OSError('Incomplete scan: a child resolves outside the selected target')
            info = os.stat(path, follow_symlinks=False)
            # Follow internal links for existence/type, but never recurse through
            # them. The link's own metadata also participates in the fingerprint.
            resolved_info = os.stat(path) if stat.S_ISLNK(info.st_mode) else info
            is_directory = stat.S_ISDIR(resolved_info.st_mode)
            if not os.access(path, os.R_OK | (os.X_OK if is_directory else 0)):
                raise PermissionError('Incomplete scan: a child is unreadable')
            relative = os.path.relpath(path, root_path).replace(os.sep, '/')
            size = 0 if is_directory else info.st_size
            digest.update(f"{'d' if is_directory else 'f'}\0{relative}\0{size}\0{info.st_mtime_ns}\n".encode())
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


def save_scan_state(library_uuid, folder_path, scan_mode, fingerprint, entry_count, total_size, *, commit=True):
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
    if commit:
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
        try:
            job = enqueue_scheduled_scan(schedule)
        except (ValueError, OSError) as exc:
            current_app.logger.warning('Schedule %s could not dispatch: %s', schedule.id, exc)
            db.session.add(SystemEvents(event_text=f'Scan schedule {schedule.id} could not dispatch: {exc}'[:256], event_type='job', event_level='warning'))
            schedule.next_run = now + timedelta(minutes=schedule.interval_minutes)
            db.session.commit()
            continue
        schedule.last_run = now
        schedule.last_job_id = job.id
        schedule.next_run = now + timedelta(minutes=schedule.interval_minutes)
        db.session.commit()
        dispatched.append(job)
    return dispatched


def enqueue_scheduled_scan(schedule, *, created_by_id=None, force=False):
    """Queue one execution without changing the schedule's recurring cadence."""
    from sharewarez.utils.background_jobs import enqueue

    options, discarded = legacy_scan_options(schedule.options if schedule.options is not None else {})
    if discarded:
        message = f'Scan schedule {schedule.id}: unsupported legacy options were discarded.'
        current_app.logger.warning(message)
        db.session.add(SystemEvents(event_text=message, event_type='job', event_level='warning'))
    extensions = db.session.execute(select(AllowedFileType.value)).scalars().all()
    target = resolve_scan_target(schedule.folder_path, schedule.scan_mode, extensions=extensions)
    payload = {
        **options,
        'library_uuid': schedule.library_uuid,
        'folder_path': target.path,
        'scan_mode': target.mode,
        'schedule_id': schedule.id,
        'force_scan': force,
    }
    return enqueue(
        'library.scan', payload, max_attempts=3, created_by_id=created_by_id,
    )
