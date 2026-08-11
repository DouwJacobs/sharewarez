from flask import render_template, redirect, url_for, flash, jsonify, current_app, abort, request
import os
from flask_login import login_required, current_user
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import DownloadRequest, GlobalSettings
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sharewarez.utils.functions import format_size
from sharewarez.utils.event_logging import log_system_event
from . import download_bp
from sharewarez import db
from sharewarez.utils.download_limits import calculate_download_expiry, expire_download_requests

@download_bp.route('/downloads')
@login_required
def downloads():
    user_id = current_user.id
    expire_download_requests(user_id)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(10, request.args.get('per_page', 25, type=int)), 100)
    query = (
        select(DownloadRequest)
        .options(joinedload(DownloadRequest.game))
        .filter_by(user_id=user_id)
        .order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
    )
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    for download_request in pagination.items:
        download_request.formatted_size = format_size(download_request.download_size)
    form = CsrfProtectForm()
    return render_template('games/manage_downloads.html', download_requests=pagination.items, pagination=pagination, form=form)

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
        log_system_event(f"User {current_user.id} cancelled download request {download_id}", event_type='audit', event_level='information')
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
        download_request.status = 'available'
        download_request.completion_time = None
        settings = db.session.execute(select(GlobalSettings)).scalars().first()
        download_request.expires_at = calculate_download_expiry(settings)
        db.session.commit()
        log_system_event(f"User {current_user.id} retried download request {download_id}", event_type='audit', event_level='information')
        flash('Download request is available again.', 'success')
    return redirect(url_for('download.downloads'))

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
    
    # Delete download request (no physical files to clean up with new streaming approach)
    flash('Download request removed.', 'info')
    
    db.session.delete(download_request)
    db.session.commit()
    
    log_system_event(f"User {current_user.id} deleted download request {download_id}", 
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
