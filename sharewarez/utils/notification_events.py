"""Canonical event registry and transactional notification fan-out."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import select

from sharewarez import db
from sharewarez.models import (
    GlobalSettings, Notification, NotificationEvent, User, WebhookDelivery,
    WebhookEndpoint,
)
from sharewarez.utils.background_jobs import enqueue


@dataclass(frozen=True)
class EventDefinition:
    label: str
    category: str
    description: str
    roles: tuple[str, ...] = ('user', 'admin')


EVENTS = {
    'new_game': EventDefinition('New games', 'games', 'A game is added to the library.'),
    'game_update': EventDefinition('Game updates', 'games', 'New update files are discovered.'),
    'download_archive_ready': EventDefinition('Downloads ready', 'downloads', 'A resumable archive is ready.'),
    'request_created': EventDefinition('New requests', 'requests', 'A request is created or joined.', ('admin',)),
    'request_updated': EventDefinition('Request updates', 'requests', 'A request changes status.', ('user',)),
    'issue_created': EventDefinition('New issues', 'issues', 'A game issue is reported.', ('admin',)),
    'issue_comment': EventDefinition('Issue replies', 'issues', 'A public issue reply is posted.'),
    'issue_status': EventDefinition('Issue status changes', 'issues', 'An issue changes status.'),
    'issue_deleted': EventDefinition('Deleted issues', 'issues', 'An issue is removed.', ('user',)),
    'download_cancelled': EventDefinition('Cancelled downloads', 'downloads', 'A user cancels a download.', ('admin',)),
    'download_repeated': EventDefinition('Repeated downloads', 'downloads', 'A request starts another transfer.', ('admin',)),
}

PERSONAL_CHANNELS = ('in_app', 'email', 'push')
INSTANCE_CHANNELS = ('in_app', 'email', 'push', 'discord')


def event_catalog():
    return EVENTS


def _settings_record():
    return db.session.execute(select(GlobalSettings)).scalars().first()


def _legacy_personal_default(user, event_type, channel):
    from sharewarez.utils.user_preferences import get_experience_settings

    definition = EVENTS[event_type]
    notifications = get_experience_settings(user)['notifications']
    if channel == 'email':
        return True
    enabled = bool(notifications.get(definition.category, True))
    if channel == 'push':
        enabled = enabled and bool(notifications.get('browser', True))
    return enabled


def personal_preferences(user):
    """Return a complete per-event matrix, filling legacy and missing values."""
    from sharewarez.utils.user_preferences import get_experience_settings

    notifications = get_experience_settings(user)['notifications']
    stored_events = notifications.get('events') if isinstance(notifications, dict) else None
    matrix = {}
    for event_type in EVENTS:
        stored = stored_events.get(event_type, {}) if isinstance(stored_events, dict) else {}
        matrix[event_type] = {
            channel: bool(stored.get(channel, _legacy_personal_default(user, event_type, channel)))
            for channel in PERSONAL_CHANNELS
        }
    return matrix


def notification_policy():
    settings = _settings_record()
    values = settings.settings if settings and isinstance(settings.settings, dict) else {}
    stored = values.get('notificationPolicy')
    stored = stored if isinstance(stored, dict) else {}
    legacy_email = {
        'request_created': bool(values.get('notifyAdminRequestEmail', False)),
        'request_updated': bool(values.get('notifyRequesterRequestEmail', True)),
        'issue_created': bool(values.get('notifyAdminIssueEmail', True)),
        'issue_comment': bool(values.get('notifyAdminIssueEmail', True) or values.get('notifyReporterIssueEmail', True)),
        'issue_status': bool(values.get('notifyAdminIssueEmail', True) or values.get('notifyReporterIssueEmail', True)),
        'issue_deleted': bool(values.get('notifyReporterIssueEmail', True)),
    }
    legacy_discord = {
        'new_game': bool(settings and settings.discord_notify_new_games),
        'game_update': bool(settings and settings.discord_notify_game_updates),
        'download_archive_ready': bool(settings and settings.discord_notify_downloads),
        'request_created': bool(values.get('notifyDiscordNewRequests', False)),
        'request_updated': bool(values.get('notifyDiscordRequestUpdates', False)),
    }
    legacy_in_app = {
        'download_cancelled': bool(values.get('notifyAdminDownloadCancellations', False)),
        'download_repeated': bool(values.get('notifyAdminRepeatDownloads', False)),
    }
    return {
        event_type: {
            channel: bool((stored.get(event_type) or {}).get(
                channel,
                (channel in {'in_app', 'push'} and legacy_in_app.get(event_type, True))
                or (channel == 'email' and legacy_email.get(event_type, False))
                or (channel == 'discord' and legacy_discord.get(event_type, False)),
            ))
            for channel in INSTANCE_CHANNELS
        }
        for event_type in EVENTS
    }


def channel_enabled(user, event_type, channel, *, policy=None):
    policy = policy or notification_policy()
    if not policy[event_type].get(channel, False):
        return False
    if channel in PERSONAL_CHANNELS:
        return personal_preferences(user)[event_type][channel]
    return True


def _absolute_url(link_url):
    settings = _settings_record()
    base = ((settings.site_url if settings else None) or 'http://127.0.0.1:5006').rstrip('/')
    if not link_url:
        return base
    return link_url if link_url.startswith(('https://', 'http://')) else f'{base}/{link_url.lstrip("/")}'


def _payload(event):
    safe_data = {
        key: value for key, value in (event.event_data or {}).items()
        if not str(key).startswith('_')
    }
    safe_message = (event.event_data or {}).get('_webhook_message', event.message)
    return {
        'version': 1,
        'id': event.id,
        'type': event.event_type,
        'occurred_at': event.created_at.isoformat(),
        'source': _absolute_url(None),
        'subject': {
            'type': event.resource_type,
            'id': event.resource_id,
        } if event.resource_type and event.resource_id else None,
        'data': {
            'title': event.title,
            'message': safe_message,
            'url': _absolute_url(event.link_url),
            **safe_data,
        },
    }


def _generic_email(user, event):
    url = _absolute_url(event.link_url)
    return (
        f'<p>Hello {escape(user.name)},</p><h1>{escape(event.title)}</h1>'
        f'<p>{escape(event.message)}</p><p><a href="{escape(url)}">View in Sharewarez</a></p>'
    )


def publish_event(
    user_ids, event_type, title, message, *, link_url=None, dedupe_key=None,
    resource_type=None, resource_id=None, event_data=None, commit=True,
    email_subject=None, email_renderer=None, enable_email=None,
    enable_discord=None, is_test=False,
    endpoint_ids=None,
):
    """Publish one logical event and atomically stage every permitted channel."""
    if event_type not in EVENTS:
        raise ValueError(f'Unknown notification event: {event_type}')
    if dedupe_key:
        existing = db.session.execute(select(NotificationEvent).where(
            NotificationEvent.event_type == event_type,
            NotificationEvent.dedupe_key == dedupe_key,
        )).scalar_one_or_none()
        if existing is not None:
            return existing

    event = NotificationEvent(
        event_type=event_type,
        title=str(title)[:255],
        message=str(message),
        link_url=link_url,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        event_data=event_data or {},
        dedupe_key=dedupe_key,
        is_test=is_test,
    )
    db.session.add(event)
    db.session.flush()
    policy = notification_policy()
    users = list(db.session.execute(select(User).where(
        User.id.in_(sorted(set(user_ids))), User.state.is_(True),
    )).scalars()) if user_ids else []

    push_ids = []
    for user in users:
        if channel_enabled(user, event_type, 'in_app', policy=policy) and not is_test:
            db.session.add(Notification(
                event_id=event.id, user_id=user.id, event_type=event_type,
                title=event.title, message=event.message, link_url=link_url,
                dedupe_key=dedupe_key,
            ))
        if channel_enabled(user, event_type, 'push', policy=policy) and not is_test:
            push_ids.append(user.id)
        email_allowed = policy[event_type]['email'] and (
            True if enable_email is None else bool(enable_email)
        )
        if email_allowed and personal_preferences(user)[event_type]['email'] and not is_test:
            html = email_renderer(user) if email_renderer else _generic_email(user, event)
            enqueue(
                'notifications.send_email',
                {'recipient': user.email, 'subject': email_subject or event.title, 'html': html},
                max_attempts=3, commit=False,
            )
    if push_ids:
        enqueue(
            'notifications.send_push',
            {'user_ids': push_ids, 'title': event.title, 'message': event.message, 'link_url': link_url},
            max_attempts=3, commit=False,
        )

    discord_allowed = policy[event_type]['discord'] and (
        True if enable_discord is None else bool(enable_discord)
    )
    if discord_allowed and not is_test:
        enqueue('notifications.send_discord', {'event_id': event.id}, max_attempts=5, commit=False)

    for endpoint in db.session.execute(select(WebhookEndpoint).where(
        WebhookEndpoint.is_enabled.is_(True)
    )).scalars():
        if endpoint_ids is not None and endpoint.id not in set(endpoint_ids):
            continue
        if event_type not in (endpoint.subscribed_events or []):
            continue
        delivery = WebhookDelivery(endpoint_id=endpoint.id, event_id=event.id, payload=_payload(event))
        db.session.add(delivery)
        db.session.flush()
        enqueue(
            'notifications.send_webhook', {'delivery_id': delivery.id},
            max_attempts=5, commit=False,
        )
    if commit:
        db.session.commit()
    return event


def cleanup_webhook_deliveries(retention_days=30):
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    deleted = db.session.query(WebhookDelivery).filter(
        WebhookDelivery.created_at < cutoff
    ).delete(synchronize_session=False)
    db.session.commit()
    return deleted
