from html import escape

from discord_webhook import DiscordEmbed, DiscordWebhook
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import GlobalSettings, User
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.game_requests import get_request_settings
from sharewarez.utils.smtp import send_email


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
    try:
        if preferences['notifyDiscordNewRequests']:
            action = 'joined' if joined_existing else 'created'
            _send_discord(record, f'Game request {action}: {record.game_name}', 'A user submitted interest in this edition.')
        if preferences['notifyAdminRequestEmail']:
            for admin in db.session.execute(select(User).where(User.role == 'admin', User.state.is_(True))).scalars():
                send_email(
                    admin.email,
                    f'Game request: {record.game_name}',
                    f'<p>A user requested <strong>{escape(record.game_name)}</strong>.</p><p><a href="{_request_url(record, admin=True)}">Review request</a></p>',
                    show_feedback=False,
                )
    except Exception as error:
        log_system_event(f'New request notification failed: {error}', event_type='game_request', event_level='error')


def notify_request_updated(record, satisfied_links=None):
    preferences = get_request_settings()
    try:
        if preferences['notifyDiscordRequestUpdates']:
            _send_discord(record, f'Request updated: {record.game_name}', record.public_response or 'The request status changed.')
        if preferences['notifyRequesterRequestEmail']:
            status = record.status.replace('_', ' ').title()
            game_link = ''
            if record.fulfilled_game_uuid:
                settings = _settings_record()
                base = ((settings.site_url if settings else None) or 'http://127.0.0.1:5006').rstrip('/')
                game_link = f'<p><a href="{base}/game_details/{record.fulfilled_game_uuid}">View available game</a></p>'
            recipients = list(satisfied_links if satisfied_links is not None else record.active_requesters)
            for link in recipients:
                if link.withdrawn_at is not None:
                    continue
                send_email(
                    link.user.email,
                    f'Your game request is {status}: {record.game_name}',
                    f'<p>Your request for <strong>{escape(record.game_name)}</strong> is now <strong>{status}</strong>.</p>'
                    f'<p>{escape(record.public_response or "")}</p>{game_link}',
                    show_feedback=False,
                )
                link.last_notified_status = record.status
            db.session.commit()
    except Exception as error:
        db.session.rollback()
        log_system_event(f'Request update notification failed: {error}', event_type='game_request', event_level='error')
