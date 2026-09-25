from sqlalchemy import select

from sharewarez import db
from sharewarez.models import GlobalSettings
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.game_requests import get_request_settings
from sharewarez.utils.email_templates import render_system_email
from sharewarez.utils.notification_events import (
    channel_enabled, notification_policy, publish_event,
)


def _settings_record():
    return db.session.execute(select(GlobalSettings)).scalars().first()


def _request_url(record, admin=False):
    settings = _settings_record()
    base = ((settings.site_url if settings else None) or 'http://127.0.0.1:5006').rstrip('/')
    return f'{base}/admin/game-requests/{record.id}' if admin else f'{base}/requests'


def notify_new_request(record, joined_existing=False):
    preferences = get_request_settings()
    request_type = getattr(record, 'request_type', 'new_game')
    req_label = {
        'update': 'Game update request',
        'issue': 'Game issue report',
    }.get(request_type, 'Game request')
    try:
        from sharewarez.utils.notifications import active_user_ids
        action = 'joined' if joined_existing else 'created'
        requesters = record.active_requesters
        requester_name = requesters[-1].user.name if requesters else 'A user'

        def render_email(user):
            return render_system_email('admin_new_request', {
                'request_type': req_label,
                'game_name': record.game_name,
                'requester_name': requester_name,
                'admin_url': _request_url(record, admin=True),
            })[1]

        publish_event(
            active_user_ids(role='admin'), 'request_created',
            f'{req_label} {action}: {record.game_name}',
            'A user joined this request.' if joined_existing else 'A new request needs review.',
            link_url=f'/admin/game-requests/{record.id}',
            dedupe_key=f'request:{record.id}:{action}:{len(record.interested_requesters)}',
            resource_type='game_request', resource_id=record.id,
            event_data={'request_type': request_type, 'status': record.status},
            enable_email=preferences['notifyAdminRequestEmail'],
            email_renderer=render_email,
            enable_discord=preferences['notifyDiscordNewRequests'],
        )
    except Exception as error:
        log_system_event(f'New request notification failed: {error}', event_type='game_request', event_level='error')


def notify_request_updated(record, satisfied_links=None):
    preferences = get_request_settings()
    try:
        recipients = list(satisfied_links if satisfied_links is not None else record.active_requesters)
        recipient_ids = {
            link.user_id for link in recipients if link.withdrawn_at is None
        }
        status = record.status.replace('_', ' ').title()

        def render_email(user):
            game_url = ''
            if record.fulfilled_game_uuid:
                game_url = _request_url(record).rsplit('/requests', 1)[0] + f'/game_details/{record.fulfilled_game_uuid}'
            return render_system_email('request_status_update', {
                'user_name': user.name, 'game_name': record.game_name,
                'status': status, 'response': record.public_response or '',
                'game_url': game_url,
            })[1]

        publish_event(
            recipient_ids, 'request_updated', f'Request updated: {record.game_name}',
            record.public_response or f'Status changed to {record.status.replace("_", " ").title()}.',
            link_url=(f'/game_details/{record.fulfilled_game_uuid}' if record.fulfilled_game_uuid else '/requests'),
            dedupe_key=f'request-update:{record.id}:{record.status}',
            resource_type='game_request', resource_id=record.id,
            event_data={'status': record.status},
            enable_email=preferences['notifyRequesterRequestEmail'],
            email_renderer=render_email,
            enable_discord=preferences['notifyDiscordRequestUpdates'],
            commit=False,
        )
        if preferences['notifyRequesterRequestEmail']:
            policy = notification_policy()
            notified_user_ids = set()
            for link in recipients:
                if (
                    link.withdrawn_at is not None
                    or link.user_id in notified_user_ids
                    or not channel_enabled(
                        link.user, 'request_updated', 'email', policy=policy,
                    )
                ):
                    continue
                notified_user_ids.add(link.user_id)
                link.last_notified_status = record.status
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        log_system_event(f'Request update notification failed: {error}', event_type='game_request', event_level='error')
