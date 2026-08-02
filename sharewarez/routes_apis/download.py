# /sharewarez/routes_apis/download.py
from typing import Tuple
from flask import jsonify, request
import os
from sqlalchemy import select
from flask_login import login_required, current_user
from sharewarez import db
from sharewarez.utils.auth import admin_required
from sharewarez.models import DownloadRequest
from sharewarez.utils.event_logging import log_system_event
from . import apis_bp

ALLOWED_BULK_ACTIONS = {'delete', 'cancel', 'retry'}

@apis_bp.route('/downloads/status')
@login_required
def download_statuses():
    raw_ids = request.args.get('ids', '')
    try:
        request_ids = sorted({int(value) for value in raw_ids.split(',') if value and int(value) > 0})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid request IDs'}), 400
    if not request_ids or len(request_ids) > 100:
        return jsonify({'status': 'error', 'message': 'Request between 1 and 100 statuses'}), 400
    query = select(DownloadRequest).where(DownloadRequest.id.in_(request_ids))
    if current_user.role != 'admin':
        query = query.where(DownloadRequest.user_id == current_user.id)
    downloads = db.session.execute(query).scalars().all()
    return jsonify({'downloads': [
        {'id': item.id, 'status': item.status, 'available': item.status == 'available'}
        for item in downloads
    ]})

@apis_bp.route('/downloads/bulk', methods=['POST'])
@login_required
@admin_required
def bulk_download_actions():
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    raw_ids = data.get('ids', [])
    if action not in ALLOWED_BULK_ACTIONS or not isinstance(raw_ids, list):
        return jsonify({'status': 'error', 'message': 'Invalid bulk action request'}), 400
    try:
        request_ids = sorted({int(value) for value in raw_ids if int(value) > 0})
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Request IDs must be positive integers'}), 400
    if not request_ids or len(request_ids) > 100:
        return jsonify({'status': 'error', 'message': 'Select between 1 and 100 requests'}), 400

    downloads = db.session.execute(
        select(DownloadRequest).where(DownloadRequest.id.in_(request_ids))
    ).scalars().all()
    changed = 0
    for download in downloads:
        if action == 'delete':
            db.session.delete(download)
            changed += 1
        elif action == 'cancel' and download.status in {'pending', 'processing'}:
            download.status = 'cancelled'
            changed += 1
        elif action == 'retry' and download.status in {'failed', 'cancelled'} and download.file_location and os.path.exists(download.file_location):
            download.status = 'available'
            download.completion_time = None
            changed += 1
    db.session.commit()
    log_system_event(
        f'Admin bulk {action} changed {changed} of {len(request_ids)} download requests',
        event_type='download_api', event_level='information'
    )
    return jsonify({'status': 'success', 'message': f'{changed} request(s) updated', 'changed': changed})

@apis_bp.route('/delete_download/<int:request_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_download_request(request_id: int) -> Tuple[dict, int]:
    """
    Delete a download request.

    Args:
        request_id: The ID of the download request to delete

    Returns:
        JSON response with status and message
    """
    # Validate request_id is positive
    if request_id <= 0:
        log_system_event('download_api', f'Invalid request ID: {request_id}', 'warning')
        return jsonify({
            'status': 'error',
            'message': 'Invalid request ID'
        }), 400
        
    try:
        download_request = db.session.get(DownloadRequest, request_id)
        if not download_request:
            return jsonify({
                'status': 'error',
                'message': 'Download request not found'
            }), 404

        # Delete the download request from database
        log_system_event(
            'download_api',
            f'Deleting download request {request_id} for user {download_request.user_id}',
            'info'
        )

        db.session.delete(download_request)
        db.session.commit()

        log_system_event('download_api', f'Successfully deleted download request {request_id}', 'info')

        return jsonify({
            'status': 'success',
            'message': 'Download request deleted successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        log_system_event(
            'download_api', 
            f'Error deleting download request {request_id}: {str(e)}', 
            'error'
        )
        return jsonify({
            'status': 'error',
            'message': f'Error deleting download request: {str(e)}'
        }), 500
