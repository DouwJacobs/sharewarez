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
    """Compatibility wrapper around the canonical event dispatcher."""
    from sharewarez.utils.notification_events import publish_event

    before = db.session.query(Notification).count()
    publish_event(
        user_ids, event_type, title, message, link_url=link_url,
        dedupe_key=dedupe_key, commit=commit,
    )
    return max(0, db.session.query(Notification).count() - before)
