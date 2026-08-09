# /sharewarez/routes_apis/scan.py
from datetime import datetime, timedelta, timezone
import os

from flask import current_app, jsonify, request
from flask_login import login_required
from sharewarez import db
from sharewarez.models import ScanJob, UnmatchedFolder, Library, LibraryScanSchedule
from sqlalchemy import select
from sharewarez.utils.auth import admin_required
from sharewarez.utils.functions import PLATFORM_IDS
from sharewarez.utils.security import get_allowed_base_directories, is_safe_path
from . import apis_bp

@apis_bp.route('/scan_jobs_status', methods=['GET'])
@login_required
@admin_required
def scan_jobs_status():
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
        'progress_percentage': round((job.folders_success + job.folders_failed) / job.total_folders * 100, 1) if job.total_folders > 0 else 0
    } for job in jobs]
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

    data = request.get_json(silent=True) or {}
    library = db.session.get(Library, data.get('library_uuid'))
    if library is None:
        return jsonify({'error': 'Library not found'}), 404
    folder_path = os.path.realpath(str(data.get('folder_path') or ''))
    allowed = get_allowed_base_directories(current_app)
    safe, message = is_safe_path(folder_path, allowed)
    if not safe:
        return jsonify({'error': message}), 400
    scan_mode = data.get('scan_mode', 'folders')
    if scan_mode not in {'folders', 'files'}:
        return jsonify({'error': 'scan_mode must be folders or files'}), 400
    try:
        interval = int(data.get('interval_minutes', 1440))
    except (TypeError, ValueError):
        return jsonify({'error': 'interval_minutes must be an integer'}), 400
    if not 15 <= interval <= 10080:
        return jsonify({'error': 'interval_minutes must be between 15 and 10080'}), 400
    schedule = LibraryScanSchedule(
        library_uuid=library.uuid, folder_path=folder_path, scan_mode=scan_mode,
        interval_minutes=interval, options=data.get('options') or {},
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
    data = request.get_json(silent=True) or {}
    if 'is_enabled' in data:
        schedule.is_enabled = bool(data['is_enabled'])
    if 'interval_minutes' in data:
        try:
            interval = int(data['interval_minutes'])
        except (TypeError, ValueError):
            return jsonify({'error': 'interval_minutes must be an integer'}), 400
        if not 15 <= interval <= 10080:
            return jsonify({'error': 'interval_minutes must be between 15 and 10080'}), 400
        schedule.interval_minutes = interval
        schedule.next_run = datetime.now(timezone.utc) + timedelta(minutes=interval)
    if 'options' in data:
        schedule.options = data['options'] or {}
    db.session.commit()
    return jsonify(_schedule_data(schedule))
