from discord_webhook import DiscordEmbed, DiscordWebhook
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import GlobalSettings, User
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.game_requests import get_request_settings
from sharewarez.utils.smtp import send_email
from sharewarez.utils.email_templates import render_system_email


def _settings_record():
    return db.session.execute(select(GlobalSettings)).scalars().first()


def _request_url(record, admin=False):
    settings = _settings_record()
    base = ((settings.site_url if settings else None) or 'http://127.0.0.1:5006').rstrip('/')
    return f'{base}/admin/game-requests/{record.id}' if admin else f'{base}/requests'


def _send_discord(record, title, description, admin_link=True):
    settings = _settings_record()
    if not settings or not settings.discord_webhook_url:
        return False
    webhook = DiscordWebhook(url=settings.discord_webhook_url, rate_limit_retry=True)
    embed = DiscordEmbed(title=title, description=description, url=_request_url(record, admin=admin_link), color='03b2f8')
    if record.cover_url:
        embed.set_thumbnail(url=record.cover_url)
    embed.add_embed_field(name='Edition', value=record.edition_name or 'Standard / base game', inline=True)
    embed.add_embed_field(name='Status', value=record.status.replace('_', ' ').title(), inline=True)
    embed.add_embed_field(name='Interested users', value=str(len(record.interested_requesters)), inline=True)
    embed.set_timestamp()
    webhook.add_embed(embed)
    webhook.execute()
    return True


def notify_new_request(record, joined_existing=False):
    preferences = get_request_settings()
    is_update = (getattr(record, 'request_type', 'new_game') == 'update')
    req_label = 'Game update request' if is_update else 'Game request'
    try:
        from sharewarez.utils.notifications import active_user_ids, create_notifications
        action = 'joined' if joined_existing else 'created'
        create_notifications(
            active_user_ids(role='admin'), 'request_created',
            f'{req_label} {action}: {record.game_name}',
            'A user joined this request.' if joined_existing else 'A new request needs review.',
            link_url=f'/admin/game-requests/{record.id}',
            dedupe_key=f'request:{record.id}:{action}:{len(record.interested_requesters)}',
        )
        if preferences['notifyDiscordNewRequests']:
            desc = 'A user requested an update for this game.' if is_update else 'A user submitted interest in this edition.'
            _send_discord(record, f'{req_label} {action}: {record.game_name}', desc)
        if preferences['notifyAdminRequestEmail']:
            requesters = record.active_requesters
            requester_name = requesters[-1].user.name if requesters else 'A user'
            subject, body = render_system_email('admin_new_request', {
                'request_type': req_label,
                'game_name': record.game_name,
                'requester_name': requester_name,
                'admin_url': _request_url(record, admin=True),
            })
            for admin in db.session.execute(select(User).where(User.role == 'admin', User.state.is_(True))).scalars():
                send_email(
                    admin.email,
                    subject,
                    body,
                    show_feedback=False,
                )
    except Exception as error:
        log_system_event(f'New request notification failed: {error}', event_type='game_request', event_level='error')


def notify_request_updated(record, satisfied_links=None):
    preferences = get_request_settings()
    try:
        from sharewarez.utils.notifications import create_notifications
        recipients = list(satisfied_links if satisfied_links is not None else record.active_requesters)
        recipient_ids = {
            link.user_id for link in recipients if link.withdrawn_at is None
        }
        create_notifications(
            recipient_ids, 'request_updated', f'Request updated: {record.game_name}',
            record.public_response or f'Status changed to {record.status.replace("_", " ").title()}.',
            link_url=(f'/game_details/{record.fulfilled_game_uuid}' if record.fulfilled_game_uuid else '/requests'),
            dedupe_key=f'request-update:{record.id}:{record.status}',
        )
        if preferences['notifyDiscordRequestUpdates']:
            _send_discord(record, f'Request updated: {record.game_name}', record.public_response or 'The request status changed.')
        if preferences['notifyRequesterRequestEmail']:
            status = record.status.replace('_', ' ').title()
            game_url = ''
            if record.fulfilled_game_uuid:
                settings = _settings_record()
                base = ((settings.site_url if settings else None) or 'http://127.0.0.1:5006').rstrip('/')
                game_url = f'{base}/game_details/{record.fulfilled_game_uuid}'
            notified_user_ids = set()
            for link in recipients:
                if link.withdrawn_at is not None or link.user_id in notified_user_ids:
                    continue
                notified_user_ids.add(link.user_id)
                subject, body = render_system_email('request_status_update', {
                    'user_name': link.user.name,
                    'game_name': record.game_name,
                    'status': status,
                    'response': record.public_response or '',
                    'game_url': game_url,
                })
                send_email(
                    link.user.email,
                    subject,
                    body,
                    show_feedback=False,
                )
                link.last_notified_status = record.status
            db.session.commit()
    except Exception as error:
        db.session.rollback()
        log_system_event(f'Request update notification failed: {error}', event_type='game_request', event_level='error')
