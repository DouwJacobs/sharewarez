from flask import render_template, redirect, url_for, flash, request, jsonify
from datetime import datetime, timezone
from flask_login import login_required
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import DownloadQueueEntry, DownloadRequest, DownloadTransfer, User
from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import joinedload
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.functions import format_duration, format_size
from sharewarez import db
from sharewarez.live_snapshots import transfer_payload
from . import download_bp

@download_bp.route('/admin/manage-downloads', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_downloads():
    page = max(1, request.args.get('page', 1, type=int))
    transfer_page = max(1, request.args.get('transfer_page', 1, type=int))
    per_page = min(max(10, request.args.get('per_page', 25, type=int)), 100)
    status_filter = request.args.get('status', '').strip().lower()
    user_filter = request.args.get('user', '').strip()
    content_type_filter = request.args.get('content_type', '').strip().lower()
    transfer_status_filter = request.args.get('transfer_status', '').strip().lower()
    filters = []
    if status_filter:
        filters.append(DownloadRequest.status == status_filter)
    if user_filter:
        filters.append(User.name.ilike(f'%{user_filter}%'))
    if content_type_filter in {'game', 'update', 'extra'}:
        filters.append(DownloadRequest.content_type == content_type_filter)
    query = (
        select(DownloadRequest)
        .options(
            joinedload(DownloadRequest.game),
            joinedload(DownloadRequest.user),
            joinedload(DownloadRequest.game_update),
            joinedload(DownloadRequest.game_extra),
        )
        .join(User, DownloadRequest.user_id == User.id)
        .order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
    )
    if filters:
        query = query.where(and_(*filters))
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)

    transfer_query = (
        select(DownloadTransfer)
        .options(
            joinedload(DownloadTransfer.user),
            joinedload(DownloadTransfer.game),
            joinedload(DownloadTransfer.download_request).joinedload(DownloadRequest.game),
        )
        .join(User, DownloadTransfer.user_id == User.id)
        .order_by(DownloadTransfer.started_at.desc(), DownloadTransfer.id.desc())
    )
    transfer_filters = []
    if user_filter:
        transfer_filters.append(User.name.ilike(f'%{user_filter}%'))
    if transfer_status_filter in {'active', 'completed', 'interrupted', 'cancelled'}:
        transfer_filters.append(DownloadTransfer.status == transfer_status_filter)
    if transfer_filters:
        transfer_query = transfer_query.where(and_(*transfer_filters))
    transfer_pagination = db.paginate(
        transfer_query, page=transfer_page, per_page=per_page, error_out=False
    )
    for transfer in transfer_pagination.items:
        transfer.formatted_bytes_sent = format_size(transfer.bytes_sent) if transfer.bytes_sent else '0 B'

    return render_template('admin/admin_manage_downloads.html', download_requests=pagination.items,
                           pagination=pagination, status_filter=status_filter, user_filter=user_filter,
                           content_type_filter=content_type_filter,
                           transfer_status_filter=transfer_status_filter,
                           transfer_pagination=transfer_pagination,
                           transfers=transfer_pagination.items)


@download_bp.route('/admin/download-transfers/<int:transfer_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_transfer(transfer_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        return jsonify({'message': 'Invalid request'}), 400
    now = datetime.now(timezone.utc)
    result = db.session.execute(
        update(DownloadTransfer)
        .where(
            DownloadTransfer.id == transfer_id,
            DownloadTransfer.status == 'active',
        )
        .values(
            status='cancelled',
            reserved_bytes=DownloadTransfer.bytes_sent,
            last_activity_at=now,
            ended_at=now,
        )
    )
    db.session.commit()
    if result.rowcount:
        log_system_event(
            f'Administrator cancelled download transfer {transfer_id}',
            event_type='download_api', event_level='warning',
        )
        flash('Transfer cancellation requested.', 'success')
    elif db.session.get(DownloadTransfer, transfer_id) is None:
        flash('Transfer attempt not found.', 'error')
    else:
        flash('Only active transfers can be cancelled.', 'warning')
    return redirect(url_for('download.manage_downloads'))


@download_bp.route('/admin/download-transfers/clear', methods=['POST'])
@login_required
@admin_required
def clear_transfer_history():
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        return jsonify({'message': 'Invalid request'}), 400
    result = db.session.execute(
        delete(DownloadTransfer).where(DownloadTransfer.status != 'active')
    )
    count = max(result.rowcount or 0, 0)
    db.session.commit()
    log_system_event(
        f'Administrator cleared {count} finished download transfer records',
        event_type='download_api', event_level='information',
    )
    flash(f'Cleared {count} transfer attempt record(s).', 'success')
    return redirect(url_for('download.manage_downloads'))


@download_bp.route('/admin/active-transfers')
@login_required
@admin_required
def active_transfers():
    transfers = db.session.execute(
        select(DownloadTransfer)
        .options(
            joinedload(DownloadTransfer.user),
            joinedload(DownloadTransfer.download_request),
        )
        .where(DownloadTransfer.status == 'active')
        .order_by(DownloadTransfer.started_at.asc(), DownloadTransfer.id.asc())
    ).scalars().all()
    now = datetime.now(timezone.utc)
    payload = [transfer_payload(transfer, now, admin=True) for transfer in transfers]
    response = jsonify({'transfers': payload})
    response.headers['Cache-Control'] = 'no-store'
    return response

@download_bp.route('/delete_download_request/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def delete_download_request(request_id):
    """
    Delete a download request via admin interface.
    """
    download_request = db.session.get(DownloadRequest, request_id)
    if not download_request:
        flash('Download request not found.', 'error')
        return redirect(url_for('download.manage_downloads'))

    active_transfer = db.session.scalar(
        select(DownloadTransfer.id).where(
            DownloadTransfer.download_request_id == request_id,
            DownloadTransfer.status == 'active',
        )
    )
    if active_transfer:
        flash('Cancel the active transfer before deleting this download link.', 'warning')
        return redirect(url_for('download.manage_downloads'))

    # Delete the download request from database
    log_system_event('admin_download', f'Admin deleting download request {request_id}', 'info')
    db.session.delete(download_request)
    db.session.commit()

    flash('Download request deleted.', 'success')
    return redirect(url_for('download.manage_downloads'))


@download_bp.route('/admin/download-priority/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def update_download_priority(request_id):
    download_request = db.session.get(DownloadRequest, request_id)
    if download_request is None:
        return jsonify({'message': 'Download request not found'}), 404

    data = request.get_json(silent=True) or {}
    priority = data.get('priority')
    if isinstance(priority, bool) or not isinstance(priority, int) or priority not in {-10, 0, 10}:
        return jsonify({'message': 'Priority must be low, normal, or high'}), 400

    download_request.priority = priority
    db.session.execute(
        update(DownloadQueueEntry)
        .where(DownloadQueueEntry.download_request_id == request_id)
        .values(priority=priority)
    )
    db.session.commit()
    log_system_event(
        f'Admin changed download request {request_id} priority to {priority}',
        event_type='download_api',
        event_level='information',
    )
    return jsonify({'message': 'Download priority updated', 'priority': priority})
