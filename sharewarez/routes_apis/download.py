# /sharewarez/routes_apis/download.py
from typing import Tuple
from flask import jsonify, request
from sqlalchemy import select
from flask_login import login_required, current_user
from sharewarez.live_snapshot_cache import invalidate_snapshots
from sharewarez.utils.download_state import lock_download
from sharewarez import db
from sharewarez.utils.auth import admin_required
from sharewarez.models import DownloadRequest, DownloadTransfer
from sqlalchemy.orm import joinedload
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.download_cache import archive_policy
from sharewarez.live_snapshots import download_payloads
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
    query = select(DownloadRequest).options(joinedload(DownloadRequest.archive)).where(
        DownloadRequest.id.in_(request_ids)
    )
    if current_user.role != 'admin':
        query = query.where(DownloadRequest.user_id == current_user.id)
    downloads = db.session.execute(query).scalars().all()
    policy = archive_policy()
    payloads = download_payloads(downloads, policy)
    response = jsonify({'downloads': payloads, 'transfers': [item['active_transfer'] for item in payloads if item['active_transfer']]})
    response.headers['Cache-Control'] = 'no-store'
    return response

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
    from sharewarez.utils.download_state import apply_action, lock_download
    changed = 0
    for item in sorted(downloads, key=lambda link: (link.user_id, link.id)):
        link = lock_download(item.id)
        if link is not None:
            accepted, _message = apply_action(link, action, admin=True)
            changed += int(accepted)
    db.session.commit()
    invalidate_snapshots()
    log_system_event(
        f'Admin bulk {action} changed {changed} of {len(request_ids)} download requests',
        event_type='download_api', event_level='information'
    )
    return jsonify({'status': 'success', 'message': f'{changed} link(s) changed; {len(request_ids) - changed} skipped', 'changed': changed, 'skipped': len(request_ids) - changed})

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
        download_request = lock_download(request_id)
        if not download_request:
            return jsonify({
                'status': 'error',
                'message': 'Download request not found'
            }), 404

        active_transfer = db.session.scalar(
            select(DownloadTransfer.id).where(
                DownloadTransfer.download_request_id == request_id,
                DownloadTransfer.status == 'active',
            )
        )
        if active_transfer is not None:
            return jsonify({
                'status': 'warning',
                'message': 'Cancel the active transfer before deleting this download link.'
            }), 409

        # Delete the download request from database
        log_system_event(
            'download_api',
            f'Deleting download request {request_id} for user {download_request.user_id}',
            'info'
        )

        db.session.delete(download_request)
        db.session.commit()
        invalidate_snapshots()

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
