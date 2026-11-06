from flask import render_template, redirect, url_for, flash, jsonify, current_app, abort, request
from flask_login import login_required, current_user
from sharewarez.forms import CsrfProtectForm
from sharewarez.models import DownloadRequest, DownloadTransfer
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sharewarez.utils.functions import format_size
from sharewarez.utils.event_logging import log_system_event
from . import download_bp
from sharewarez import db
from sharewarez.utils.download_notifications import notify_admin_download_cancelled

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
    from sharewarez.utils.download_state import download_states
    state_counts = {}
    for item, state in zip(pagination.items, download_states(pagination.items)):
        item.view = state
        label = state['display_status']
        state_counts[label] = state_counts.get(label, 0) + 1
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
    from sharewarez.utils.download_state import attempt_payload
    response = jsonify({'transfers': [attempt_payload(transfer) for transfer in transfers]})
    response.headers['Cache-Control'] = 'no-store'
    return response

def _change_link(download_id, action):
    from sharewarez.utils.download_state import apply_action, lock_download
    form = CsrfProtectForm()
    if not form.validate_on_submit():
        return jsonify({'message': 'Invalid request'}), 400
    link = lock_download(download_id, owner_id=current_user.id)
    if link is None:
        label = 'deletion' if action == 'delete' else action
        log_system_event(f'Unauthorized download {label} attempt: user {current_user.id}, request {download_id}', event_type='security', event_level='warning')
        abort(404)
    changed, message = apply_action(link, action)
    if not changed:
        db.session.rollback()
        flash(message, 'warning')
        return redirect(url_for('download.downloads'))
    db.session.commit()
    event = f'User {current_user.name} deleted download request {download_id}' if action == 'delete' else f'User {current_user.id} applied {action} to download request {download_id}'
    log_system_event(event, event_type='audit')
    if action == 'cancel':
        try:
            notify_admin_download_cancelled(link, current_user.name)
        except Exception:
            current_app.logger.warning('Download cancellation notification failed for request %s', download_id)
    flash(message, 'success')
    return redirect(url_for('download.download_zip', download_id=download_id) if action == 'fallback' else url_for('download.downloads'))


@download_bp.route('/downloads/<int:download_id>/cancel', methods=['POST'])
@login_required
def cancel_download(download_id):
    return _change_link(download_id, 'cancel')


@download_bp.route('/downloads/<int:download_id>/retry', methods=['POST'])
@login_required
def retry_download(download_id):
    return _change_link(download_id, 'retry')


@download_bp.route('/downloads/<int:download_id>/stream-without-resume', methods=['POST'])
@login_required
def stream_without_resume(download_id):
    return _change_link(download_id, 'fallback')


@download_bp.route('/delete_download/<int:download_id>', methods=['POST'])
@login_required
def delete_download(download_id):
    return _change_link(download_id, 'delete')

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
        from sharewarez.live_snapshots import download_payload
        from sharewarez.utils.download_cache import archive_policy
        return jsonify({
            'status': download_request.status,
            'downloadId': download_request.id,
            'found': True,
            'download': download_payload(download_request, archive_policy())
        })
    
    # Log unauthorized access attempt
    log_system_event(f"Unauthorized download status check: user {current_user.id} tried to check download {download_id}", 
                    event_type='security', event_level='warning')
    
    return jsonify({
        'status': 'not_found',
        'downloadId': download_id,
        'found': False
    }), 404
