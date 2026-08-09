from datetime import datetime, timezone

from flask import jsonify, request
from flask_login import login_required
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import BackgroundJob
from sharewarez.utils.auth import admin_required
from . import apis_bp


def _serialize(job):
    return {
        'id': job.id, 'task_name': job.task_name, 'queue': job.queue,
        'status': job.status, 'progress': job.progress,
        'progress_message': job.progress_message, 'attempts': job.attempts,
        'max_attempts': job.max_attempts,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'heartbeat_at': job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        'cancel_requested': job.cancel_requested, 'error_message': job.error_message,
        'created_by_id': job.created_by_id,
    }


@apis_bp.route('/background-jobs', methods=['GET'])
@login_required
@admin_required
def background_jobs():
    limit = min(max(request.args.get('limit', 50, type=int), 1), 200)
    status = (request.args.get('status') or '').strip().lower()
    query = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
    if status:
        query = query.where(BackgroundJob.status == status)
    jobs = db.session.execute(query).scalars().all()
    return jsonify({'jobs': [_serialize(job) for job in jobs]})


@apis_bp.route('/background-jobs/<job_id>', methods=['GET'])
@login_required
@admin_required
def background_job(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    data = _serialize(job)
    data['result'] = job.result
    return jsonify(data)


@apis_bp.route('/background-jobs/<job_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_background_job(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    if job.status not in {'queued', 'running'}:
        return jsonify({'error': 'Job is not cancellable'}), 409
    job.cancel_requested = True
    if job.status == 'queued':
        job.status = 'cancelled'
        job.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_serialize(job))


@apis_bp.route('/background-jobs/<job_id>/retry', methods=['POST'])
@login_required
@admin_required
def retry_background_job(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    if job.status not in {'failed', 'cancelled'}:
        return jsonify({'error': 'Only failed or cancelled jobs can be retried'}), 409
    job.status = 'queued'
    job.cancel_requested = False
    job.attempts = 0
    job.available_at = datetime.now(timezone.utc)
    job.started_at = job.completed_at = job.heartbeat_at = None
    job.locked_by = None
    job.error_message = None
    job.progress = 0
    job.progress_message = 'Retry queued'
    db.session.commit()
    return jsonify(_serialize(job))
