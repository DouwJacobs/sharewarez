"""Durable scan ownership, terminal details and administrator operations."""
from datetime import datetime, timezone

from sqlalchemy import select, or_

from sharewarez import db
from sharewarez.models import BackgroundJob, ScanJob, UnmatchedFolder
from sharewarez.utils.scan_targets import SCAN_OPTIONS, legacy_scan_options


class ScanRunError(RuntimeError):
    """A recorded scan failure that must propagate to the queue executor."""


def create_scan_detail(path, mode, library_uuid, options, job=None):
    detail = ScanJob(
        library_uuid=library_uuid, scan_folder=path, folders={path: True},
        content_type='Games', status='Running', is_enabled=True,
        last_run=datetime.now(timezone.utc), error_message='',
        setting_remove=options.get('remove_missing') is True,
        setting_filefolder=mode == 'files',
        setting_download_missing_images=options.get('download_missing_images') is True,
        setting_force_updates_extras=options.get('force_updates_extras_scan') is True,
        scan_options=dict(options), background_job_id=job.id if job else None,
    )
    db.session.add(detail)
    db.session.flush()
    if job:
        job.payload = {**(job.payload or {}), 'scan_job_id': detail.id}
    db.session.commit()
    return detail


def finish_scan(detail_id, outcome, message='', counts=None):
    detail = db.session.get(ScanJob, detail_id, populate_existing=True)
    if detail is None:
        raise ScanRunError('Scan detail disappeared before finalization.')
    detail.status = 'Completed' if outcome in {'completed', 'skipped'} else 'Failed'
    detail.outcome = outcome
    detail.error_message = str(message or '')[:4000]
    detail.current_processing = None
    detail.last_progress_update = datetime.now(timezone.utc)
    if counts:
        for key, value in counts.items():
            setattr(detail, key, value)
    db.session.commit()
    return {
        'scan_job_id': detail.id, 'outcome': outcome,
        'total': detail.total_folders, 'matched': detail.folders_success,
        'unmatched': detail.folders_unmatched, 'failed': detail.folders_failed,
        'processed': detail.folders_success + detail.folders_unmatched + detail.folders_failed,
        'removed': detail.removed_count,
    }


def scan_is_active(detail):
    if detail.status in {'Scheduled', 'Running', 'Stopping'}:
        return True
    for job_id in (detail.background_job_id, detail.replacement_job_id):
        job = db.session.get(BackgroundJob, job_id, populate_existing=True) if job_id else None
        if job and job.status in {'queued', 'running'}:
            return True
    return False


def cancel_scan(detail):
    from sharewarez.utils.background_jobs import cancel_job

    replacement = db.session.get(BackgroundJob, detail.replacement_job_id) if detail.replacement_job_id else None
    job_id = replacement.id if replacement and replacement.status in {'queued', 'running'} else detail.background_job_id
    job = db.session.get(BackgroundJob, job_id) if job_id else None
    if job and job.status in {'queued', 'running'}:
        cancel_job(job)
        return job
    if detail.status not in {'Running', 'Stopping', 'Scheduled'}:
        raise ValueError('Scan is not cancellable.')
    # Compatibility for an old web-owned execution. New starts use the queue.
    detail.is_enabled = False
    detail.status = 'Stopping'
    detail.error_message = 'Cancellation requested. No removals performed.'
    db.session.commit()
    return None


def restart_scan(detail_id, *, created_by_id=None):
    from sharewarez.utils.background_jobs import enqueue

    detail = db.session.execute(select(ScanJob).where(ScanJob.id == detail_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if detail is None:
        raise LookupError('Scan not found.')
    if detail.replacement_job_id:
        replacement = db.session.get(BackgroundJob, detail.replacement_job_id, populate_existing=True)
        if replacement and replacement.status in {'queued', 'running'}:
            db.session.commit()
            return replacement
    if scan_is_active(detail):
        db.session.rollback()
        raise ValueError('Cannot restart an active scan.')
    options, _ = legacy_scan_options(detail.scan_options or {})
    # Historical rows did not store HLTB overrides; both default to False.
    defaults = dict.fromkeys(SCAN_OPTIONS, False)
    defaults.update(
        remove_missing=bool(detail.setting_remove),
        download_missing_images=bool(detail.setting_download_missing_images),
        force_updates_extras_scan=bool(detail.setting_force_updates_extras),
    )
    defaults.update(options)
    payload = {
        **defaults, 'library_uuid': detail.library_uuid,
        'folder_path': detail.scan_folder,
        'scan_mode': 'files' if detail.setting_filefolder else 'folders',
        'force_scan': True, 'restart_of_scan_id': detail.id,
    }
    replacement = enqueue('library.scan', payload, max_attempts=3, created_by_id=created_by_id, commit=False)
    detail.replacement_job_id = replacement.id
    db.session.commit()
    return replacement


def delete_scan_history(detail_ids):
    """Delete eligible terminal details; retain active and unmatched references."""
    # Match retry/cancel lock order: durable owner first, then its detail.
    references = db.session.execute(select(ScanJob.background_job_id, ScanJob.replacement_job_id).where(ScanJob.id.in_(detail_ids))).all()
    owner_ids = {value for pair in references for value in pair if value}
    if owner_ids:
        db.session.execute(select(BackgroundJob).where(BackgroundJob.id.in_(owner_ids)).order_by(BackgroundJob.id).with_for_update()).scalars().all()
    deleted = retained = 0
    for detail in db.session.execute(select(ScanJob).where(ScanJob.id.in_(detail_ids)).order_by(ScanJob.id).with_for_update().execution_options(populate_existing=True)).scalars():
        referenced = db.session.execute(select(UnmatchedFolder.id).where(UnmatchedFolder.scan_job_id == detail.id).limit(1)).first()
        if scan_is_active(detail) or referenced:
            retained += 1
        else:
            db.session.delete(detail)
            deleted += 1
    db.session.commit()
    return deleted, retained


def mark_scan_cancellation(job):
    """Run after the durable cancellation has committed, preserving lock order."""
    for detail in db.session.execute(select(ScanJob).where(ScanJob.background_job_id == job.id, or_(ScanJob.status.in_(['Running', 'Stopping', 'Scheduled']), ((ScanJob.id == (job.payload or {}).get('scan_job_id')) & ScanJob.outcome.in_(['completed', 'skipped'])) if job.status == 'cancelled' else False))).scalars():
        detail.is_enabled = False
        if job.status == 'cancelled':
            detail.status = 'Failed'
            detail.outcome = 'cancelled'
            detail.current_processing = None
        else:
            detail.status = 'Stopping'
        detail.error_message = 'Cancellation requested. No removals performed.'
    db.session.commit()


def recover_scan_details(job_ids=None, *, all_running=False):
    query = select(ScanJob).where(ScanJob.status.in_(['Running', 'Stopping']))
    if not all_running:
        query = query.where(ScanJob.background_job_id.in_(job_ids or []))
    for detail in db.session.execute(query).scalars():
        owner = db.session.get(BackgroundJob, detail.background_job_id) if detail.background_job_id else None
        detail.status = 'Failed'
        detail.outcome = 'cancelled' if owner and owner.cancel_requested else 'interrupted'
        detail.error_message = 'Scan interrupted by worker restart. No removals performed.'
        detail.is_enabled = False
        detail.current_processing = None
    db.session.commit()


def mark_scan_failed(job_id, message):
    job = db.session.get(BackgroundJob, job_id)
    detail_id = (job.payload or {}).get('scan_job_id') if job else None
    detail = db.session.get(ScanJob, detail_id, populate_existing=True) if detail_id else None
    if detail and detail.outcome not in {'failed', 'partial', 'cancelled', 'interrupted'}:
        finish_scan(detail.id, 'partial' if detail.folders_success + detail.folders_unmatched else 'failed', message)
