"""Administrator controls for the managed resumable archive cache."""

from datetime import datetime, timezone
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from sharewarez.live_snapshots import cache_payload

from sharewarez import cache, db
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import (
    BackgroundJob, DownloadArchive, DownloadRequest, DownloadTransfer, GlobalSettings,
)
from sharewarez.routes_admin_ext.settings import (
    update_settings_fields, validate_settings_data,
)
from sharewarez.utils.auth import admin_required
from sharewarez.utils.background_jobs import cancel_job, enqueue
from sharewarez.utils.download_cache import (
    acquire_archive_lease, archive_policy, archive_summary, cleanup_cache,
    resolved_archive_path,
)
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.functions import format_size
from . import download_bp


CACHE_POLICY_FIELDS = {
    'archiveCacheMode', 'archiveCacheMaxGb', 'archiveCacheMinFreeGb',
    'archiveCacheRetentionDays', 'archiveCacheBuildConcurrency',
    'archiveCacheFallbackEnabled',
}


def _archive_or_404(archive_id):
    archive = db.session.get(DownloadArchive, archive_id)
    if archive is None:
        abort(404)
    return archive


@download_bp.route('/admin/download-cache')
@login_required
@admin_required
def manage_download_cache():
    page = max(1, request.args.get('page', 1, type=int))
    state = request.args.get('state', '').strip().lower()
    query_text = request.args.get('q', '').strip()
    statement = select(DownloadArchive).options(joinedload(DownloadArchive.build_job)).order_by(
        DownloadArchive.updated_at.desc(), DownloadArchive.created_at.desc()
    )
    if state in {'queued', 'building', 'ready', 'failed'}:
        statement = statement.where(DownloadArchive.state == state)
    if query_text:
        statement = statement.where(DownloadArchive.display_name.ilike(f'%{query_text}%'))
    pagination = db.paginate(statement, page=page, per_page=25, error_out=False)
    active_counts = dict(db.session.execute(
        select(DownloadTransfer.archive_id, func.count(DownloadTransfer.id)).where(
            DownloadTransfer.status == 'active', DownloadTransfer.archive_id.is_not(None),
        ).group_by(DownloadTransfer.archive_id)
    ).all())
    for archive in pagination.items:
        archive.formatted_source_bytes = format_size(archive.source_bytes)
        archive.formatted_archive_bytes = format_size(archive.archive_bytes)
        archive.formatted_bytes_written = format_size(archive.bytes_written)
        archive.active_leases = active_counts.get(archive.id, 0)
        build_job = archive.build_job
        archive.cancel_requested = bool(build_job and build_job.cancel_requested)
        archive.progress = (
            min(99, max(0, build_job.progress))
            if build_job and archive.state in {'queued', 'building'} else None
        )
        archive.progress_message = build_job.progress_message if build_job else None
    summary = archive_summary()
    for key in ('used_bytes', 'ready_bytes', 'reclaimable_bytes'):
        summary[f'formatted_{key}'] = format_size(summary[key])
    summary['formatted_free_bytes'] = format_size(summary['health']['free_bytes'])
    return render_template(
        'admin/admin_download_cache.html', archives=pagination.items,
        pagination=pagination, summary=summary, policy=summary['policy'],
        state_filter=state, query_text=query_text, form=CsrfProtectForm(),
    )


@download_bp.route('/admin/download-cache/status')
@login_required
@admin_required
def download_cache_status():
    raw_ids = request.args.get('ids')
    if raw_ids is not None:
        ids = list(set(filter(None, raw_ids.split(','))))
        if len(ids) > 100 or any(len(value) > 36 for value in ids):
            return jsonify({'error': 'Invalid archive IDs'}), 400
        response = jsonify(cache_payload(ids))
        response.headers['Cache-Control'] = 'no-store'
        return response
    summary = archive_summary()
    return jsonify({
        'status': 'success',
        'data': {
            'healthy': summary['health']['healthy'],
            'message': summary['health']['message'],
            'used_bytes': summary['used_bytes'],
            'free_bytes': summary['health']['free_bytes'],
            'counts': summary['counts'],
        },
    })


@download_bp.route('/admin/download-cache/policy', methods=['POST'])
@login_required
@admin_required
def update_download_cache_policy():
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    values = {
        'archiveCacheMode': request.form.get('archiveCacheMode', 'prefer'),
        'archiveCacheMaxGb': request.form.get('archiveCacheMaxGb', type=float),
        'archiveCacheMinFreeGb': request.form.get('archiveCacheMinFreeGb', type=float),
        'archiveCacheRetentionDays': request.form.get('archiveCacheRetentionDays', type=int),
        'archiveCacheBuildConcurrency': request.form.get('archiveCacheBuildConcurrency', type=int),
        'archiveCacheFallbackEnabled': request.form.get('archiveCacheFallbackEnabled') == 'on',
    }
    errors = validate_settings_data(values)
    if errors:
        flash(' '.join(errors), 'error')
        return redirect(url_for('download.manage_download_cache'))
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db.session.add(settings)
    update_settings_fields(settings, values)
    db.session.commit()
    cache.delete('global_settings')
    log_system_event(
        f'Archive cache policy updated by {current_user.name}',
        event_type='audit', event_level='information',
    )
    flash('Archive cache policy updated.', 'success')
    return redirect(url_for('download.manage_download_cache'))


@download_bp.route('/admin/download-cache/cleanup', methods=['POST'])
@login_required
@admin_required
def run_download_cache_cleanup():
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    result = cleanup_cache(clear_unused=request.form.get('clear_unused') == 'true')
    log_system_event(
        f'Archive cache cleanup removed {result["removed"]} entries and {result["removed_bytes"]} bytes',
        event_type='audit', event_level='information',
    )
    flash(f'Removed {result["removed"]} cache entr{"y" if result["removed"] == 1 else "ies"}.', 'success')
    return redirect(url_for('download.manage_download_cache'))


@download_bp.route('/admin/download-cache/entries/<archive_id>/pin', methods=['POST'])
@login_required
@admin_required
def pin_download_archive(archive_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    archive = _archive_or_404(archive_id)
    archive.pinned = request.form.get('pinned') == 'true'
    archive.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Cache entry pinned.' if archive.pinned else 'Cache entry unpinned.', 'success')
    return redirect(url_for('download.manage_download_cache'))


@download_bp.route('/admin/download-cache/entries/<archive_id>/retry', methods=['POST'])
@login_required
@admin_required
def retry_download_archive(archive_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    archive = _archive_or_404(archive_id)
    if archive.state in {'queued', 'building', 'ready'}:
        flash('This cache entry does not need to be retried.', 'warning')
        return redirect(url_for('download.manage_download_cache'))
    archive.state = 'queued'
    archive.failure_code = archive.failure_message = None
    job = enqueue(
        'download.archive.build', {'archive_id': archive.id}, queue='archive',
        max_attempts=3, created_by_id=current_user.id, commit=False,
    )
    archive.build_job_id = job.id
    db.session.query(DownloadRequest).filter(
        DownloadRequest.archive_id == archive.id,
        DownloadRequest.status == 'failed',
    ).update({'status': 'processing'}, synchronize_session=False)
    db.session.commit()
    flash('Archive preparation queued again.', 'success')
    return redirect(url_for('download.manage_download_cache'))


@download_bp.route('/admin/download-cache/entries/<archive_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_download_archive(archive_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    archive = _archive_or_404(archive_id)
    if archive.state not in {'queued', 'building'}:
        flash('This cache build is no longer running.', 'warning')
        return redirect(url_for('download.manage_download_cache'))

    job = db.session.get(BackgroundJob, archive.build_job_id) if archive.build_job_id else None
    if job is None or job.status not in {'queued', 'running'}:
        archive.state = 'failed'
        archive.build_job_id = None
        archive.failure_code = 'build_cancelled'
        archive.failure_message = 'Archive preparation was cancelled by an administrator.'
        archive.updated_at = datetime.now(timezone.utc)
        db.session.query(DownloadRequest).filter(
            DownloadRequest.archive_id == archive.id,
            DownloadRequest.status == 'processing',
        ).update({'status': 'failed'}, synchronize_session=False)
        db.session.commit()
        message = 'Archive preparation cancelled.'
    else:
        was_running = job.status == 'running'
        cancel_job(job)
        message = (
            'Cancellation requested. The partial file will be removed safely.'
            if was_running else 'Archive preparation cancelled.'
        )
    log_system_event(
        f'Administrator {current_user.name} cancelled archive cache build {archive_id}',
        event_type='audit', event_level='information',
    )
    flash(message, 'success')
    return redirect(url_for('download.manage_download_cache'))


@download_bp.route('/admin/download-cache/entries/<archive_id>', methods=['POST'])
@login_required
@admin_required
def evict_download_archive(archive_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        abort(400)
    archive = _archive_or_404(archive_id)
    active = db.session.scalar(select(func.count(DownloadTransfer.id)).where(
        DownloadTransfer.archive_id == archive.id, DownloadTransfer.status == 'active',
    ))
    if active or archive.state in {'queued', 'building'}:
        flash('Active or preparing cache entries cannot be evicted.', 'warning')
        return redirect(url_for('download.manage_download_cache'))
    lease = acquire_archive_lease(archive.id)
    if lease is None:
        flash('This archive is currently in use and cannot be evicted.', 'warning')
        return redirect(url_for('download.manage_download_cache'))
    try:
        if archive.relative_path:
            resolved_archive_path(archive, require_ready=False).unlink(missing_ok=True)
        policy = archive_policy()
        fallback = policy['archiveCacheMode'] != 'require' and policy['archiveCacheFallbackEnabled']
        db.session.query(DownloadRequest).filter(
            DownloadRequest.archive_id == archive.id,
        ).update(
            {
                'archive_id': None,
                'delivery_kind': 'live_archive' if fallback else 'cached_archive',
                'status': 'available' if fallback else 'failed',
            },
            synchronize_session=False,
        )
        label = archive.display_name
        db.session.delete(archive)
        db.session.commit()
        log_system_event(
            f'Administrator {current_user.name} evicted cached archive {archive_id}',
            event_type='audit', event_level='information',
        )
        flash(f'Evicted {label}. Source files were not changed.', 'success')
        return redirect(url_for('download.manage_download_cache'))
    finally:
        lease.release()
