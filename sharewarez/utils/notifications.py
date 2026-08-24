"""Durable, idempotent in-app notification delivery."""

from sqlalchemy import select

from sharewarez import db
from sharewarez.models import Notification, User


def active_user_ids(role=None):
    statement = select(User.id).where(User.state.is_(True))
    if role:
        statement = statement.where(User.role == role)
    return list(db.session.execute(statement).scalars())


def create_notifications(user_ids, event_type, title, message, link_url=None,
                         dedupe_key=None, commit=True):
    """Create one inbox item per user, skipping an already-delivered event key."""
    user_ids = sorted(set(user_ids))
    if not user_ids:
        return 0
    users = {
        user.id: user for user in db.session.execute(
            select(User).where(User.id.in_(user_ids))
        ).scalars()
    }
    from sharewarez.utils.user_preferences import notification_enabled
    user_ids = [
        user_id for user_id in user_ids
        if user_id in users and notification_enabled(users[user_id], event_type)
    ]
    if not user_ids:
        return 0
    existing = set()
    if dedupe_key:
        existing = set(db.session.execute(
            select(Notification.user_id).where(
                Notification.user_id.in_(user_ids),
                Notification.dedupe_key == dedupe_key,
            )
        ).scalars())
    created = 0
    created_user_ids = []
    for user_id in user_ids:
        if user_id in existing:
            continue
        db.session.add(Notification(
            user_id=user_id,
            event_type=event_type,
            title=title[:255],
            message=message,
            link_url=link_url,
            dedupe_key=dedupe_key,
        ))
        created += 1
        created_user_ids.append(user_id)
    if commit and created:
        db.session.commit()
        try:
            from sharewarez.utils.web_push import send_push_notifications
            push_user_ids = [
                user_id for user_id in created_user_ids
                if notification_enabled(users[user_id], event_type, browser=True)
            ]
            if push_user_ids:
                send_push_notifications(push_user_ids, title, message, link_url)
        except Exception:
            # Browser push is best-effort; the durable in-app notification remains authoritative.
            pass
    return created
