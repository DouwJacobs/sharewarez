"""Notifications for the standalone game issue workflow."""

from sqlalchemy import select

from sharewarez import db
from sharewarez.models import GlobalSettings, User
from sharewarez.utils.email_templates import render_system_email
from sharewarez.utils.background_jobs import enqueue
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.notifications import active_user_ids, create_notifications


def _settings():
    record = db.session.execute(select(GlobalSettings)).scalars().first()
    values = record.settings if record and isinstance(record.settings, dict) else {}
    return record, values


def _base_url(record):
    return ((record.site_url if record else None) or 'http://127.0.0.1:5006').rstrip('/')


def _send_issue_email(user, issue, heading, message, admin=False):
    settings, _ = _settings()
    path = f'/admin/issues/{issue.id}' if admin else f'/issues/{issue.id}'
    subject, body = render_system_email('issue_activity', {
        'user_name': user.name,
        'heading': heading,
        'game_name': issue.game.name,
        'issue_title': issue.title,
        'message': message,
        'issue_url': f'{_base_url(settings)}{path}',
    })
    enqueue(
        'notifications.send_email',
        {'recipient': user.email, 'subject': subject, 'html': body},
        max_attempts=3,
    )
    return True


def notify_issue_created(issue):
    """Notify every active administrator about a new issue."""
    try:
        admin_ids = active_user_ids(role='admin')
        create_notifications(
            admin_ids,
            'issue_created',
            f'New issue: {issue.game.name}',
            f'{issue.reporter.name}: {issue.title}',
            link_url=f'/admin/issues/{issue.id}',
            dedupe_key=f'issue:{issue.id}:created',
        )
        _, values = _settings()
        if values.get('notifyAdminIssueEmail', True):
            admins = db.session.execute(
                select(User).where(User.id.in_(admin_ids))
            ).scalars()
            for admin in admins:
                _send_issue_email(
                    admin,
                    issue,
                    'A new game issue needs review',
                    f'{issue.reporter.name} reported: {issue.description}',
                    admin=True,
                )
    except Exception as error:
        db.session.rollback()
        log_system_event(
            f'New issue notification failed: {error}',
            event_type='game_issue', event_level='error',
        )


def notify_issue_comment(issue, comment):
    """Notify the other side when a public comment is added."""
    if comment.is_internal:
        return
    try:
        author_is_admin = comment.author and comment.author.role == 'admin'
        if author_is_admin:
            recipient_ids = [issue.reporter_id]
            link_url = f'/issues/{issue.id}'
            title = f'Admin replied: {issue.game.name}'
            email_recipients = [issue.reporter]
            admin_link = False
        else:
            recipient_ids = [
                user_id for user_id in active_user_ids(role='admin')
                if user_id != comment.author_id
            ]
            link_url = f'/admin/issues/{issue.id}'
            title = f'User replied: {issue.game.name}'
            email_recipients = list(db.session.execute(
                select(User).where(User.id.in_(recipient_ids))
            ).scalars())
            admin_link = True
        create_notifications(
            recipient_ids,
            'issue_comment',
            title,
            comment.body[:240],
            link_url=link_url,
            dedupe_key=f'issue:{issue.id}:comment:{comment.id}',
        )
        _, values = _settings()
        setting_key = 'notifyReporterIssueEmail' if author_is_admin else 'notifyAdminIssueEmail'
        if values.get(setting_key, True):
            for recipient in email_recipients:
                _send_issue_email(
                    recipient,
                    issue,
                    title,
                    comment.body,
                    admin=admin_link,
                )
    except Exception as error:
        db.session.rollback()
        log_system_event(
            f'Issue comment notification failed: {error}',
            event_type='game_issue', event_level='error',
        )


def notify_issue_status(issue, previous_status, activity):
    """Notify the reporter and administrators about a status transition."""
    try:
        actor_is_admin = activity.author and activity.author.role == 'admin'
        if actor_is_admin:
            recipient_ids = [issue.reporter_id]
            recipients = [issue.reporter]
            link_url = f'/issues/{issue.id}'
            admin_link = False
        else:
            recipient_ids = active_user_ids(role='admin')
            recipients = list(db.session.execute(
                select(User).where(User.id.in_(recipient_ids))
            ).scalars())
            link_url = f'/admin/issues/{issue.id}'
            admin_link = True
        status_label = issue.status.replace('_', ' ').title()
        message = f'Status changed from {previous_status.replace("_", " ").title()} to {status_label}.'
        create_notifications(
            recipient_ids,
            'issue_status',
            f'Issue {status_label}: {issue.game.name}',
            message,
            link_url=link_url,
            dedupe_key=f'issue:{issue.id}:status:{activity.id}',
        )
        _, values = _settings()
        setting_key = 'notifyReporterIssueEmail' if actor_is_admin else 'notifyAdminIssueEmail'
        if values.get(setting_key, True):
            for recipient in recipients:
                _send_issue_email(
                    recipient,
                    issue,
                    f'Issue status changed to {status_label}',
                    message,
                    admin=admin_link,
                )
    except Exception as error:
        db.session.rollback()
        log_system_event(
            f'Issue status notification failed: {error}',
            event_type='game_issue', event_level='error',
        )


def notify_issue_deleted(issue, actor_name):
    try:
        create_notifications(
            [issue.reporter_id],
            'issue_deleted',
            f'Issue removed: {issue.game.name}',
            f'{actor_name} removed “{issue.title}”.',
            link_url='/issues',
            dedupe_key=f'issue:{issue.id}:deleted',
        )
    except Exception as error:
        db.session.rollback()
        log_system_event(
            f'Issue deletion notification failed: {error}',
            event_type='game_issue', event_level='error',
        )
