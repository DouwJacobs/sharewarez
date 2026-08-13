from datetime import datetime, timezone

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, update

from sharewarez import db
from sharewarez.models import Notification


notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/notifications')
@login_required
def notification_center():
    page = request.args.get('page', 1, type=int)
    unread_only = request.args.get('filter') == 'unread'
    statement = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    pagination = db.paginate(
        statement.order_by(Notification.created_at.desc()),
        page=max(page, 1), per_page=30, error_out=False,
    )
    return render_template(
        'site/notifications.html', notifications=pagination.items,
        pagination=pagination, unread_only=unread_only,
    )


@notifications_bp.route('/notifications/<int:notification_id>/open', methods=['POST'])
@login_required
def open_notification(notification_id):
    notification = db.session.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    ).scalar_one_or_none() or abort(404)
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.session.commit()
    target = notification.link_url or url_for('notifications.notification_center')
    if not target.startswith('/') or target.startswith('//'):
        target = url_for('notifications.notification_center')
    return redirect(target)


@notifications_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = db.session.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    ).scalar_one_or_none() or abort(404)
    notification.read_at = notification.read_at or datetime.now(timezone.utc)
    db.session.commit()
    return redirect(request.referrer or url_for('notifications.notification_center'))


@notifications_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    db.session.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.session.commit()
    return redirect(url_for('notifications.notification_center'))
