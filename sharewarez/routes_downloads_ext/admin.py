from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, abort
from datetime import datetime, timezone
from flask_login import current_user, login_required
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import DownloadQueueEntry, DownloadRequest, DownloadTransfer
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez import db
from sharewarez.live_snapshots import transfer_payload
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sharewarez.utils.admin_delivery import DeliveryFilters, delivery_page, finished_count, finished_query
from sharewarez.live_snapshot_cache import invalidate_snapshots
from sharewarez.utils.download_state import lock_download
from . import download_bp

@download_bp.route('/admin/manage-downloads', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_downloads():
    return render_template('admin/admin_manage_downloads.html', **delivery_context())


def parsed_filters(args):
    try:
        return DeliveryFilters.parse(args)
    except (ValueError, TypeError):
        abort(400, 'Invalid delivery filters')


def history_signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='admin-hide-finished-attempts')


def delivery_context():
    filters = parsed_filters(request.args)
    pagination = delivery_page(filters)
    context = dict(filters=filters, pagination=pagination,
                   download_requests=pagination.items if filters.view == 'links' else [],
                   transfers=pagination.items if filters.view == 'activity' else [])
    if filters.view == 'activity':
        now = datetime.now(timezone.utc)
        context['metrics'] = {item.id: transfer_payload(item, now, admin=True) for item in pagination.items}
        count = finished_count(filters)
        context.update(hide_count=count, hide_token=history_signer().dumps(
            dict(actor=current_user.id, filters=filters.params(), count=count)))
    return context


@download_bp.get('/admin/download-delivery/status')
@login_required
@admin_required
def delivery_status():
    context = delivery_context()
    response = jsonify(html=render_template('admin/_delivery_results.html', **context),
                       total=context['pagination'].total, view=context['filters'].view)
    response.headers['Cache-Control'] = 'no-store'
    return response


@download_bp.route('/admin/download-transfers/<int:transfer_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_transfer(transfer_id):
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        return jsonify({'message': 'Invalid request'}), 400
    filters = parsed_filters(request.form)
    now = datetime.now(timezone.utc)
    result = db.session.execute(
        update(DownloadTransfer)
        .where(
            DownloadTransfer.id == transfer_id,
            DownloadTransfer.status == 'active',
        )
        .values(
            status='cancelled',
            end_reason='admin_stop',
            ended_by_user_id=current_user.id,
            reserved_bytes=DownloadTransfer.bytes_sent,
            last_activity_at=now,
            ended_at=now,
        )
    )
    db.session.commit()
    invalidate_snapshots()
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
    return redirect(filters.url())


@download_bp.route('/admin/download-transfers/clear', methods=['POST'])
@login_required
@admin_required
def clear_transfer_history():
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        return jsonify({'message': 'Invalid request'}), 400
    filters = parsed_filters(request.form)
    if filters.view != 'activity' or not all(key in request.form for key in filters.params()):
        abort(400, 'Review the exact activity filters before hiding attempts')
    try:
        reviewed = history_signer().loads(request.form.get('review_token', ''), max_age=3600)
    except BadSignature:
        abort(400, 'Review the matching count before hiding attempts')
    if reviewed.get('actor') != current_user.id or reviewed.get('filters') != filters.params():
        abort(400, 'The reviewed filters have changed')
    result = db.session.execute(update(DownloadTransfer).where(
        DownloadTransfer.id.in_(finished_query(filters)),
        DownloadTransfer.admin_history_hidden_at.is_(None),
        DownloadTransfer.status.in_(('completed', 'interrupted', 'cancelled')),
    ).values(admin_history_hidden_at=datetime.now(timezone.utc)))
    count = max(result.rowcount or 0, 0)
    if count != reviewed.get('count'):
        db.session.rollback()
        abort(409, 'Matching history changed; reload and review the count again')
    db.session.commit()
    invalidate_snapshots()
    log_system_event(
        f'Administrator {current_user.id} hid {count} finished download attempts',
        event_type='download_api', event_level='information',
    )
    flash(f'Hidden {count} finished attempt(s). Transfer and quota records retained.', 'success')
    return redirect(filters.url())


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
    download_request = lock_download(request_id)
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
    invalidate_snapshots()

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
    invalidate_snapshots()
    log_system_event(
        f'Admin changed download request {request_id} priority to {priority}',
        event_type='download_api',
        event_level='information',
    )
    return jsonify({'message': 'Download priority updated', 'priority': priority})
