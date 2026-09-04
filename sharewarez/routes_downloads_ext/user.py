from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, jsonify, current_app, abort, request
import os
from flask_login import login_required, current_user
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import DownloadRequest, DownloadTransfer, GlobalSettings
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sharewarez.utils.functions import format_size
from sharewarez.utils.event_logging import log_system_event
from . import download_bp
from sharewarez import db
from sharewarez.utils.download_limits import (
    calculate_download_expiry,
)
from sharewarez.utils.download_notifications import notify_admin_download_cancelled
from sharewarez.utils.download_cache import archive_policy, request_resumable_archive

@download_bp.route('/downloads')
@login_required
def downloads():
    user_id = current_user.id
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(10, request.args.get('per_page', 25, type=int)), 100)
    query = (
        select(DownloadRequest)
        .options(joinedload(DownloadRequest.game), joinedload(DownloadRequest.archive))
        .filter_by(user_id=user_id)
        .order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
    )
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    request_ids = [item.id for item in pagination.items]
    active_by_request = {
        transfer.download_request_id: transfer
        for transfer in db.session.execute(
            select(DownloadTransfer).where(
                DownloadTransfer.user_id == user_id,
                DownloadTransfer.status == 'active',
                DownloadTransfer.download_request_id.in_(request_ids),
            )
        ).scalars()
    } if request_ids else {}
    now = datetime.now(timezone.utc)
    cache_policy = archive_policy()
    status_labels = {
        'pending': 'Queued', 'processing': 'Preparing', 'available': 'Ready',
        'failed': 'Failed', 'cancelled': 'Cancelled', 'expired': 'Expired',
    }
    state_counts = {}
    for download_request in pagination.items:
        download_request.active_transfer = active_by_request.get(download_request.id)
        if download_request.active_transfer:
            transfer = download_request.active_transfer
            transfer.formatted_bytes_sent = format_size(transfer.bytes_sent) if transfer.bytes_sent else '0 B'
            transfer.formatted_expected_bytes = format_size(transfer.reserved_bytes) if transfer.reserved_bytes else None
        download_request.formatted_size = format_size(download_request.download_size)
        archive = download_request.archive
        download_request.archive_progress = (
            min(99, round(archive.bytes_written / archive.source_bytes * 100))
            if archive and archive.source_bytes and archive.state in {'queued', 'building'} else None
        )
        is_direct_file = bool(
            download_request.delivery_kind == 'direct'
            and download_request.file_location
            and os.path.isfile(download_request.file_location)
        )
        download_request.delivery_label = (
            'Preparing' if archive and archive.state in {'queued', 'building'}
            else 'Resumable' if is_direct_file or (
                download_request.delivery_kind == 'cached_archive'
                and archive and archive.state == 'ready'
            )
            else 'Streaming · restart required'
        )
        download_request.fallback_available = bool(
            download_request.archive
            and cache_policy['archiveCacheMode'] == 'prefer'
            and cache_policy['archiveCacheFallbackEnabled']
        )
        download_request.display_status = (
            'Downloading' if download_request.active_transfer else
            status_labels.get(download_request.status, download_request.status.replace('_', ' ').title())
        )
        expiry = download_request.expires_at
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        download_request.expiring_soon = bool(
            download_request.status == 'available' and expiry and 0 < (expiry - now).total_seconds() <= 86400
        )
        state_counts[download_request.display_status] = state_counts.get(download_request.display_status, 0) + 1
    form = CsrfProtectForm()
    return render_template(
        'games/manage_downloads.html', download_requests=pagination.items,
        pagination=pagination, form=form, state_counts=state_counts,
    )


@download_bp.route('/downloads/active-transfers')
@login_required
def user_active_transfers():
    transfers = db.session.execute(
        select(DownloadTransfer).where(
            DownloadTransfer.user_id == current_user.id,
            DownloadTransfer.status == 'active',
            DownloadTransfer.download_request_id.is_not(None),
        )
    ).scalars().all()
    response = jsonify({'transfers': [{
        'download_request_id': transfer.download_request_id,
        'bytes_sent': transfer.bytes_sent,
        'expected_bytes': transfer.reserved_bytes,
        'bytes_sent_label': format_size(transfer.bytes_sent) if transfer.bytes_sent else '0 B',
        'expected_bytes_label': format_size(transfer.reserved_bytes) if transfer.reserved_bytes else None,
        'progress': (
            min(100, round(transfer.bytes_sent / transfer.reserved_bytes * 100, 1))
            if transfer.reserved_bytes else None
        ),
    } for transfer in transfers]})
    response.headers['Cache-Control'] = 'no-store'
    return response

@download_bp.route('/downloads/<int:download_id>/cancel', methods=['POST'])
@login_required
def cancel_download(download_id):
    download_request = db.session.execute(
        select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)
    ).scalar_one_or_none()
    if not download_request:
        abort(404)
    if download_request.status not in {'pending', 'processing'}:
        flash('Only pending or processing requests can be cancelled.', 'warning')
    else:
        download_request.status = 'cancelled'
        db.session.commit()
        try:
            notify_admin_download_cancelled(download_request, current_user.name)
        except Exception as error:
            log_system_event(
                f"Download cancellation notification failed: {error}",
                event_type='notification', event_level='error',
            )
        log_system_event(f"User {current_user.name} cancelled download request {download_id}", event_type='audit', event_level='information')
        flash('Download request cancelled.', 'success')
    return redirect(url_for('download.downloads'))

@download_bp.route('/downloads/<int:download_id>/retry', methods=['POST'])
@login_required
def retry_download(download_id):
    download_request = db.session.execute(
        select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)
    ).scalar_one_or_none()
    if not download_request:
        abort(404)
    if download_request.status not in {'failed', 'cancelled', 'expired'}:
        flash('This request cannot be retried.', 'warning')
    elif not download_request.file_location or not os.path.exists(download_request.file_location):
        flash('The source file is no longer available.', 'error')
    else:
        if os.path.isdir(download_request.file_location):
            download_request.archive_id = None
            request_resumable_archive(download_request)
        else:
            download_request.status = 'available'
            download_request.delivery_kind = 'direct'
        download_request.completion_time = None
        settings = db.session.execute(select(GlobalSettings)).scalars().first()
        download_request.expires_at = calculate_download_expiry(settings)
        db.session.commit()
        log_system_event(f"User {current_user.name} retried download request {download_id}", event_type='audit', event_level='information')
        flash(
            'Resumable download preparation queued.'
            if download_request.status == 'processing'
            else 'Download request is available again.',
            'success',
        )
    return redirect(url_for('download.downloads'))


@download_bp.route('/downloads/<int:download_id>/stream-without-resume', methods=['POST'])
@login_required
def stream_without_resume(download_id):
    download_request = db.session.execute(
        select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)
    ).scalar_one_or_none()
    if not download_request:
        abort(404)
    policy = archive_policy()
    if (
        policy['archiveCacheMode'] != 'prefer'
        or not policy['archiveCacheFallbackEnabled']
        or not download_request.file_location
        or not os.path.isdir(download_request.file_location)
    ):
        flash('Streaming fallback is not available for this download.', 'warning')
        return redirect(url_for('download.downloads'))
    download_request.delivery_kind = 'live_archive'
    download_request.archive_id = None
    download_request.status = 'available'
    db.session.commit()
    log_system_event(
        f'User {current_user.name} selected non-resumable fallback for request {download_id}',
        event_type='audit', event_level='information',
    )
    return redirect(url_for('download.download_zip', download_id=download_request.id))

@download_bp.route('/delete_download/<int:download_id>', methods=['POST'])
@login_required
def delete_download(download_id):
    # Validate download_id parameter
    try:
        download_id = int(download_id)
    except (ValueError, TypeError):
        log_system_event(f"Invalid download_id parameter: {download_id}", 
                        event_type='security', event_level='warning')
        abort(400)
    
    download_request = db.session.execute(select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)).scalars().first()
    
    if not download_request:
        log_system_event(f"Unauthorized download deletion attempt: user {current_user.id} tried to delete download {download_id}", 
                        event_type='security', event_level='warning')
        abort(404)

    active_transfer = db.session.execute(
        select(DownloadTransfer).where(
            DownloadTransfer.download_request_id == download_request.id,
            DownloadTransfer.status == 'active',
        )
    ).scalars().first()
    if active_transfer:
        flash('This request cannot be deleted while its download is active.', 'warning')
        return redirect(url_for('download.downloads'))
    
    # Delete download request (no physical files to clean up with new streaming approach)
    flash('Download request removed.', 'info')
    
    db.session.delete(download_request)
    db.session.commit()
    
    log_system_event(f"User {current_user.name} deleted download request {download_id}",
                   event_type='audit', event_level='information')

    return redirect(url_for('download.downloads'))

@download_bp.route('/check_download_status/<download_id>')
@login_required
def check_download_status(download_id):
    # Validate download_id parameter
    try:
        download_id = int(download_id)
    except (ValueError, TypeError):
        log_system_event(f"Invalid download_id parameter in status check: {download_id}", 
                        event_type='security', event_level='warning')
        return jsonify({
            'status': 'invalid',
            'downloadId': download_id,
            'found': False,
            'error': 'Invalid download ID'
        }), 400
    
    download_request = db.session.execute(select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)).scalars().first()
    
    if download_request:
        return jsonify({
            'status': download_request.status,
            'downloadId': download_request.id,
            'found': True
        })
    
    # Log unauthorized access attempt
    log_system_event(f"Unauthorized download status check: user {current_user.id} tried to check download {download_id}", 
                    event_type='security', event_level='warning')
    
    return jsonify({
        'status': 'not_found',
        'downloadId': download_id,
        'found': False
    }), 404
