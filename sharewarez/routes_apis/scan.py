# /sharewarez/routes_apis/scan.py
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request, url_for
from flask_login import login_required
from sharewarez import db
from sharewarez.models import ScanJob, UnmatchedFolder, Library, LibraryScanSchedule, AllowedFileType, BackgroundJob
from sqlalchemy import select
from sharewarez.utils.auth import admin_required
from sharewarez.utils.functions import PLATFORM_IDS
from sharewarez.utils.scan_targets import resolve_scan_target, validate_scan_options
from . import apis_bp

@apis_bp.route('/scan_jobs_status', methods=['GET'])
@login_required
@admin_required
def scan_jobs_status():
    from sharewarez.utils.scan_lifecycle import scan_is_active
    jobs = db.session.execute(select(ScanJob).order_by(ScanJob.last_run.desc())).scalars().all()
    jobs_data = [{
        'id': job.id,
        'library_name': job.library.name if job.library else 'No Library Assigned',
        'library_uuid': job.library_uuid,
        'folders': job.folders,
        'status': job.status,
        'total_folders': job.total_folders,
        'folders_success': job.folders_success,
        'folders_failed': job.folders_failed,
        'folders_unmatched': job.folders_unmatched,
        'outcome': job.outcome,
        'display_status': {'partial': 'Partial', 'cancelled': 'Cancelled', 'interrupted': 'Interrupted', 'skipped': 'Skipped'}.get(job.outcome, job.status),
        'background_job_id': job.background_job_id,
        'job_url': url_for('admin2.background_jobs', q=job.background_job_id) if job.background_job_id else None,
        'can_restart': not scan_is_active(job),
        'is_active': job.status in {'Running', 'Stopping', 'Scheduled'},
        'cancel_url': url_for('main.cancel_scan_job', job_id=job.id) if job.status in {'Running', 'Stopping', 'Scheduled'} else None,
        'restart_url': url_for('main.restart_scan_job', job_id=job.id),
        'removed_count': job.removed_count,
        'scan_folder': job.scan_folder,
        'setting_remove': bool(job.setting_remove),
        'setting_filefolder': bool(job.setting_filefolder),
        'setting_download_missing_images': bool(job.setting_download_missing_images),
        'current_processing': job.current_processing,
        'error_message': job.error_message or '',
        'last_run': job.last_run.strftime('%Y-%m-%d %H:%M:%S') if job.last_run else 'Not Available',
        'last_update': job.last_progress_update.isoformat() if job.last_progress_update else None,
        'next_run': job.next_run.strftime('%Y-%m-%d %H:%M:%S') if job.next_run else 'Not Scheduled',
        'progress_percentage': round((job.folders_success + job.folders_failed + job.folders_unmatched) / job.total_folders * 100, 1) if job.total_folders > 0 else 0
    } for job in jobs]
    active_owners = {job.background_job_id for job in jobs if job.status in {'Running', 'Stopping', 'Scheduled'}}
    for queued in db.session.execute(select(BackgroundJob).where(BackgroundJob.task_name == 'library.scan')).scalars():
        if queued.id in active_owners:
            continue
        payload = queued.payload or {}
        if queued.status not in {'queued', 'running'} and payload.get('scan_job_id'):
            continue
        library = db.session.get(Library, payload.get('library_uuid'))
        jobs_data.append({
            'id': queued.id, 'library_name': library.name if library else 'Deleted library',
            'library_uuid': payload.get('library_uuid'), 'scan_folder': payload.get('folder_path'),
            'status': ('Stopping' if queued.cancel_requested else 'Running') if queued.status == 'running' else queued.status.title(),
            'display_status': ('Stopping' if queued.cancel_requested else 'Finalizing') if queued.status == 'running' else queued.status.title(),
            'total_folders': 0, 'folders_success': 0, 'folders_failed': 0, 'folders_unmatched': 0,
            'current_processing': queued.progress_message, 'error_message': queued.error_message or '',
            'last_run': queued.created_at.isoformat(), 'progress_percentage': queued.progress,
            'background_job_id': queued.id, 'is_active': queued.status in {'queued', 'running'}, 'can_restart': False,
            'job_url': url_for('admin2.background_jobs', q=queued.id),
            'cancel_url': url_for('main.cancel_scan_job', job_id=queued.id) if queued.status in {'queued', 'running'} else None, 'restart_url': None,
        })
    return jsonify(jobs_data)

@apis_bp.route('/unmatched_folders', methods=['GET'])
@login_required
@admin_required
def unmatched_folders():
    unmatched = db.session.execute(
        select(UnmatchedFolder, Library.name.label('library_name'), Library.platform)
        .join(Library)
        .order_by(UnmatchedFolder.status.desc())
    ).all()
    
    unmatched_data = [{
        'id': folder.id,
        'folder_path': folder.folder_path,
        'status': folder.status,
        'library_name': library_name,
        'platform_name': platform.name if platform else '',
        'platform_id': PLATFORM_IDS.get(platform.name) if platform else None
    } for folder, library_name, platform in unmatched]
    
    return jsonify(unmatched_data)


def _schedule_data(schedule):
    return {
        'id': schedule.id, 'library_uuid': schedule.library_uuid,
        'library_name': schedule.library.name if schedule.library else None,
        'folder_path': schedule.folder_path, 'scan_mode': schedule.scan_mode,
        'interval_minutes': schedule.interval_minutes, 'options': schedule.options or {},
        'is_enabled': schedule.is_enabled,
        'next_run': schedule.next_run.isoformat() if schedule.next_run else None,
        'last_run': schedule.last_run.isoformat() if schedule.last_run else None,
        'last_job_id': schedule.last_job_id,
    }


@apis_bp.route('/scan-schedules', methods=['GET', 'POST'])
@login_required
@admin_required
def scan_schedules():
    if request.method == 'GET':
        schedules = db.session.execute(
            select(LibraryScanSchedule).order_by(LibraryScanSchedule.next_run.asc())
        ).scalars().all()
        return jsonify({'schedules': [_schedule_data(item) for item in schedules]})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Expected a JSON object'}), 400
    library = db.session.get(Library, data.get('library_uuid'))
    if library is None:
        return jsonify({'error': 'Library not found'}), 404
    scan_mode = data.get('scan_mode', 'folders')
    try:
        options = validate_scan_options(data.get('options', {}))
        if 'is_enabled' in data and type(data['is_enabled']) is not bool:
            raise ValueError('is_enabled must be a boolean')
        extensions = db.session.execute(select(AllowedFileType.value)).scalars().all()
        folder_path = resolve_scan_target(data.get('folder_path'), scan_mode, extensions=extensions).path
    except (ValueError, OSError) as exc:
        return jsonify({'error': str(exc)}), 400
    try:
        interval = int(data.get('interval_minutes', 1440))
    except (TypeError, ValueError):
        return jsonify({'error': 'interval_minutes must be an integer'}), 400
    if not 15 <= interval <= 10080:
        return jsonify({'error': 'interval_minutes must be between 15 and 10080'}), 400
    schedule = LibraryScanSchedule(
        library_uuid=library.uuid, folder_path=folder_path, scan_mode=scan_mode,
        interval_minutes=interval, options=options,
        is_enabled=bool(data.get('is_enabled', True)),
        next_run=datetime.now(timezone.utc) + timedelta(minutes=interval),
    )
    db.session.add(schedule)
    db.session.commit()
    return jsonify(_schedule_data(schedule)), 201


@apis_bp.route('/scan-schedules/<schedule_id>', methods=['PATCH', 'DELETE'])
@login_required
@admin_required
def scan_schedule(schedule_id):
    schedule = db.session.get(LibraryScanSchedule, schedule_id)
    if schedule is None:
        return jsonify({'error': 'Schedule not found'}), 404
    if request.method == 'DELETE':
        db.session.delete(schedule)
        db.session.commit()
        return '', 204
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Expected a JSON object'}), 400
    changes = {}
    try:
        if 'options' in data:
            changes['options'] = validate_scan_options(data['options'])
        if 'is_enabled' in data:
            if type(data['is_enabled']) is not bool:
                raise ValueError('is_enabled must be a boolean')
            changes['is_enabled'] = data['is_enabled']
        if any(key in data for key in ('library_uuid', 'folder_path', 'scan_mode')):
            library_uuid = data.get('library_uuid', schedule.library_uuid)
            if db.session.get(Library, library_uuid) is None:
                return jsonify({'error': 'Library not found'}), 404
            extensions = db.session.execute(select(AllowedFileType.value)).scalars().all()
            target = resolve_scan_target(data.get('folder_path', schedule.folder_path), data.get('scan_mode', schedule.scan_mode), extensions=extensions)
            changes.update(library_uuid=library_uuid, folder_path=target.path, scan_mode=target.mode)
        if 'interval_minutes' in data:
            interval = int(data['interval_minutes'])
            if not 15 <= interval <= 10080:
                raise ValueError('interval_minutes must be between 15 and 10080')
            changes.update(interval_minutes=interval, next_run=datetime.now(timezone.utc) + timedelta(minutes=interval))
    except (TypeError, ValueError, OSError) as exc:
        return jsonify({'error': str(exc)}), 400
    for key, value in changes.items():
        setattr(schedule, key, value)
    db.session.commit()
    return jsonify(_schedule_data(schedule))
