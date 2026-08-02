from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from sharewarez.models import DownloadRequest, User
from sqlalchemy import select, and_
from sqlalchemy.orm import joinedload
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez import db
from . import download_bp

@download_bp.route('/admin/manage-downloads', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_downloads():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(10, request.args.get('per_page', 25, type=int)), 100)
    status_filter = request.args.get('status', '').strip().lower()
    user_filter = request.args.get('user', '').strip()
    filters = []
    if status_filter:
        filters.append(DownloadRequest.status == status_filter)
    if user_filter:
        filters.append(User.name.ilike(f'%{user_filter}%'))
    query = (
        select(DownloadRequest)
        .options(joinedload(DownloadRequest.game), joinedload(DownloadRequest.user))
        .join(User, DownloadRequest.user_id == User.id)
        .order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
    )
    if filters:
        query = query.where(and_(*filters))
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)

    return render_template('admin/admin_manage_downloads.html', download_requests=pagination.items,
                           pagination=pagination, status_filter=status_filter, user_filter=user_filter)

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

    # Delete the download request from database
    log_system_event('admin_download', f'Admin deleting download request {request_id}', 'info')
    db.session.delete(download_request)
    db.session.commit()

    flash('Download request deleted.', 'success')
    return redirect(url_for('download.manage_downloads'))
