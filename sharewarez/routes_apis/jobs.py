from flask import jsonify, request
from flask_login import login_required
from sqlalchemy import func, or_, select

from sharewarez import db
from sharewarez.models import BackgroundJob
from sharewarez.utils.auth import admin_required
from sharewarez.utils.background_jobs import cancel_job, job_display_name, retry_job
from . import apis_bp


def _serialize(job):
    return {
        'id': job.id, 'task_name': job.task_name,
        'display_name': job_display_name(job.task_name), 'queue': job.queue,
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
    search = (request.args.get('q') or '').strip()[:100]
    visible_ids = [value for value in request.args.getlist('job_id') if value][:200]
    query = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
    if status:
        query = query.where(BackgroundJob.status == status)
    if search:
        pattern = f'%{search}%'
        query = query.where(or_(
            BackgroundJob.task_name.ilike(pattern),
            BackgroundJob.queue.ilike(pattern),
            BackgroundJob.id.ilike(pattern),
            BackgroundJob.progress_message.ilike(pattern),
            BackgroundJob.error_message.ilike(pattern),
        ))
    jobs = db.session.execute(query).scalars().all()
    if visible_ids:
        visible_jobs = db.session.execute(
            select(BackgroundJob).where(BackgroundJob.id.in_(visible_ids))
        ).scalars().all()
        jobs_by_id = {job.id: job for job in jobs}
        jobs_by_id.update({job.id: job for job in visible_jobs})
        jobs = list(jobs_by_id.values())
    counts = dict(db.session.execute(
        select(BackgroundJob.status, func.count(BackgroundJob.id))
        .group_by(BackgroundJob.status)
    ).all())
    return jsonify({'jobs': [_serialize(job) for job in jobs], 'counts': counts})


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
    try:
        cancel_job(job)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 409
    return jsonify(_serialize(job))


@apis_bp.route('/background-jobs/<job_id>/retry', methods=['POST'])
@login_required
@admin_required
def retry_background_job(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    try:
        retry_job(job)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 409
    return jsonify(_serialize(job))
