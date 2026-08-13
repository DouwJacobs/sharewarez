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
    existing = set()
    if dedupe_key:
        existing = set(db.session.execute(
            select(Notification.user_id).where(
                Notification.user_id.in_(user_ids),
                Notification.dedupe_key == dedupe_key,
            )
        ).scalars())
    created = 0
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
    if commit and created:
        db.session.commit()
    return created
