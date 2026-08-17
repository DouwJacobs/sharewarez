from datetime import datetime, timedelta, timezone
import os

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select

from sharewarez import db
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import BackgroundJob, Library, LibraryScanSchedule
from sharewarez.utils.auth import admin_required
from sharewarez.utils.background_jobs import cancel_job, job_display_name, retry_job
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.incremental_scanning import SCHEDULE_INTERVALS, enqueue_scheduled_scan
from sharewarez.utils.security import get_allowed_base_directories, is_safe_path

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
    schedules = db.session.execute(
        select(LibraryScanSchedule).order_by(
            LibraryScanSchedule.is_enabled.desc(), LibraryScanSchedule.next_run.asc()
        )
    ).scalars().all()
    return render_template(
        'admin/admin_background_jobs.html', pagination=pagination,
        counts=counts, statuses=JOB_STATUSES, status_filter=status,
        search=search, per_page=per_page, csrf_form=CsrfProtectForm(),
        job_display_name=job_display_name,
        schedules=schedules, schedule_intervals=SCHEDULE_INTERVALS,
    )


@admin2_bp.route('/admin/scan-schedules', methods=['POST'])
@login_required
@admin_required
def create_scan_schedule():
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)

    library = db.session.get(Library, request.form.get('library_uuid'))
    if library is None:
        flash('Select a valid library.', 'error')
        return redirect(url_for('main.scan_management', active_tab='auto'))

    folder_input = (request.form.get('folder_path') or '').strip()
    if os.path.isabs(folder_input):
        folder_path = os.path.realpath(folder_input)
    else:
        base_dir = current_app.config.get(
            'BASE_FOLDER_WINDOWS' if os.name == 'nt' else 'BASE_FOLDER_POSIX'
        )
        folder_path = os.path.realpath(os.path.join(base_dir or '', folder_input))
    safe, message = is_safe_path(folder_path, get_allowed_base_directories(current_app))
    if not safe:
        flash(f'Cannot schedule this folder: {message}', 'error')
        return redirect(url_for('main.scan_management', active_tab='auto'))
    if not os.path.isdir(folder_path) or not os.access(folder_path, os.R_OK):
        flash('The scan folder does not exist or is not readable.', 'error')
        return redirect(url_for('main.scan_management', active_tab='auto'))

    scan_mode = request.form.get('scan_mode', 'folders')
    if scan_mode not in {'folders', 'files'}:
        abort(400)
    try:
        interval = int(request.form.get('interval_minutes', 1440))
    except (TypeError, ValueError):
        abort(400)
    if interval not in SCHEDULE_INTERVALS:
        abort(400)

    first_run_text = (request.form.get('first_run') or '').strip()
    try:
        next_run = (
            datetime.fromisoformat(first_run_text).replace(tzinfo=timezone.utc)
            if first_run_text else datetime.now(timezone.utc) + timedelta(minutes=interval)
        )
    except ValueError:
        flash('Enter a valid first-run date and time.', 'error')
        return redirect(url_for('main.scan_management', active_tab='auto'))
    if next_run <= datetime.now(timezone.utc):
        flash('The first run must be in the future.', 'error')
        return redirect(url_for('main.scan_management', active_tab='auto'))

    options = {
        name: request.form.get(name) == 'on'
        for name in (
            'remove_missing', 'download_missing_images', 'force_updates_extras_scan',
            'fetch_hltb', 'force_hltb_refetch',
        )
    }
    schedule = LibraryScanSchedule(
        library_uuid=library.uuid, folder_path=folder_path, scan_mode=scan_mode,
        interval_minutes=interval, options=options, next_run=next_run,
    )
    db.session.add(schedule)
    db.session.commit()
    log_system_event(f'Scheduled recurring scan for {library.name}: {schedule.id}', event_type='job')
    flash(f'Scheduled scan created for {library.name}.', 'success')
    return redirect(url_for('main.scan_management', active_tab='auto'))


def _get_schedule_or_404(schedule_id):
    schedule = db.session.get(LibraryScanSchedule, schedule_id)
    if schedule is None:
        abort(404)
    return schedule


@admin2_bp.route('/admin/scan-schedules/<schedule_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_scan_schedule(schedule_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    schedule = _get_schedule_or_404(schedule_id)
    schedule.is_enabled = not schedule.is_enabled
    if schedule.is_enabled and schedule.next_run <= datetime.now(timezone.utc):
        schedule.next_run = datetime.now(timezone.utc) + timedelta(minutes=schedule.interval_minutes)
    db.session.commit()
    flash('Scan schedule resumed.' if schedule.is_enabled else 'Scan schedule paused.', 'success')
    return redirect(url_for('main.scan_management', active_tab='auto'))


@admin2_bp.route('/admin/scan-schedules/<schedule_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_scan_schedule(schedule_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    schedule = _get_schedule_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    flash('Scan schedule deleted.', 'success')
    return redirect(url_for('main.scan_management', active_tab='auto'))


@admin2_bp.route('/admin/scan-schedules/<schedule_id>/run', methods=['POST'])
@login_required
@admin_required
def run_scan_schedule(schedule_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    schedule = _get_schedule_or_404(schedule_id)
    job = enqueue_scheduled_scan(schedule, created_by_id=current_user.id)
    schedule.last_job_id = job.id
    db.session.commit()
    log_system_event(f'Scheduled scan run manually: {schedule.id} (job {job.id})', event_type='job')
    flash(f'Scan queued for {schedule.library.name}.', 'success')
    return redirect(url_for('main.scan_management', active_tab='auto'))


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
