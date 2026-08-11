from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func, or_, select

from sharewarez import db
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import BackgroundJob
from sharewarez.utils.auth import admin_required
from sharewarez.utils.background_jobs import cancel_job, job_display_name, retry_job
from sharewarez.utils.event_logging import log_system_event

from . import admin2_bp


JOB_STATUSES = ('queued', 'running', 'completed', 'failed', 'cancelled')


@admin2_bp.route('/admin/background-jobs')
@login_required
@admin_required
def background_jobs():
    status = (request.args.get('status') or '').strip().lower()
    if status not in JOB_STATUSES:
        status = ''
    search = (request.args.get('q') or '').strip()[:100]
    page = max(request.args.get('page', 1, type=int), 1)
    per_page = min(max(request.args.get('per_page', 25, type=int), 10), 100)

    query = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
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
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    counts = dict(db.session.execute(
        select(BackgroundJob.status, func.count(BackgroundJob.id))
        .group_by(BackgroundJob.status)
    ).all())
    return render_template(
        'admin/admin_background_jobs.html', pagination=pagination,
        counts=counts, statuses=JOB_STATUSES, status_filter=status,
        search=search, per_page=per_page, csrf_form=CsrfProtectForm(),
        job_display_name=job_display_name,
    )


def _get_job_or_404(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if job is None:
        abort(404)
    return job


@admin2_bp.route('/admin/background-jobs/<job_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_background_job(job_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    job = _get_job_or_404(job_id)
    try:
        cancel_job(job)
    except ValueError as exc:
        flash(str(exc), 'warning')
    else:
        log_system_event(f'Background job cancellation requested: {job.id}', event_type='job')
        flash('Cancellation requested.', 'success')
    return redirect(url_for('admin2.background_jobs'))


@admin2_bp.route('/admin/background-jobs/<job_id>/retry', methods=['POST'])
@login_required
@admin_required
def retry_background_job(job_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    job = _get_job_or_404(job_id)
    try:
        retry_job(job)
    except ValueError as exc:
        flash(str(exc), 'warning')
    else:
        log_system_event(f'Background job retried: {job.id}', event_type='job')
        flash('Job queued for retry.', 'success')
    return redirect(url_for('admin2.background_jobs'))
