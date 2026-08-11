from __future__ import annotations

from dataclasses import dataclass
from html import escape

from jinja2 import StrictUndefined, meta
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import GlobalSettings, SystemEmailTemplate


MAX_SUBJECT_LENGTH = 255
MAX_HTML_LENGTH = 50_000
GLOBAL_VARIABLES = ('site_title', 'site_url')


@dataclass(frozen=True)
class EmailTemplateDefinition:
    key: str
    name: str
    description: str
    icon: str
    subject: str
    html: str
    variables: tuple[str, ...]
    sample_context: dict[str, str]


TEMPLATE_DEFINITIONS = {
    'account_confirmation': EmailTemplateDefinition(
        key='account_confirmation',
        name='Account confirmation',
        description='Sent after registration so a new user can verify their email address.',
        icon='fa-user-check',
        subject='Confirm your {{ site_title }} account',
        html='''
<h1>Confirm your email</h1>
<p>Hello {{ user_name }},</p>
<p>Thanks for creating an account with <strong>{{ site_title }}</strong>. Confirm your email address to finish setting up your account.</p>
<p><a class="email-button" href="{{ confirm_url }}">Confirm your email</a></p>
<p class="email-muted">This link expires in {{ expires_in }}. If you did not create this account, you can safely ignore this message.</p>
'''.strip(),
        variables=('user_name', 'confirm_url', 'expires_in'),
        sample_context={
            'user_name': 'Alex',
            'confirm_url': 'https://games.example/confirm/sample-token',
            'expires_in': '15 minutes',
        },
    ),
    'password_reset': EmailTemplateDefinition(
        key='password_reset',
        name='Password reset',
        description='Sent when a user requests a secure password-reset link.',
        icon='fa-key',
        subject='Reset your {{ site_title }} password',
        html='''
<h1>Reset your password</h1>
<p>Hello {{ user_name }},</p>
<p>We received a request to reset your <strong>{{ site_title }}</strong> password.</p>
<p><a class="email-button" href="{{ reset_url }}">Choose a new password</a></p>
<p class="email-muted">This link expires in {{ expires_in }}. If you did not request a password reset, you can safely ignore this email.</p>
'''.strip(),
        variables=('user_name', 'reset_url', 'expires_in'),
        sample_context={
            'user_name': 'Alex',
            'reset_url': 'https://games.example/reset_password/sample-token',
            'expires_in': '15 minutes',
        },
    ),
    'user_invitation': EmailTemplateDefinition(
        key='user_invitation',
        name='User invitation',
        description='Sent when an existing user invites someone to join the instance.',
        icon='fa-envelope-open-text',
        subject="You're invited to {{ site_title }}",
        html='''
<h1>Join {{ site_title }}</h1>
<p>Hello,</p>
<p><strong>{{ inviter_name }}</strong> invited {{ recipient_email }} to join {{ site_title }}.</p>
<p><a class="email-button" href="{{ invite_url }}">Complete your registration</a></p>
<p class="email-muted">This invitation expires in {{ expires_in }}.</p>
'''.strip(),
        variables=('inviter_name', 'recipient_email', 'invite_url', 'expires_in'),
        sample_context={
            'inviter_name': 'Morgan',
            'recipient_email': 'alex@example.com',
            'invite_url': 'https://games.example/register?token=sample-token',
            'expires_in': '48 hours',
        },
    ),
    'admin_new_request': EmailTemplateDefinition(
        key='admin_new_request',
        name='New request for administrators',
        description='Sent to active administrators when request email notifications are enabled.',
        icon='fa-paper-plane',
        subject='{{ request_type }}: {{ game_name }}',
        html='''
<h1>New {{ request_type|lower }}</h1>
<p><strong>{{ requester_name }}</strong> submitted interest in <strong>{{ game_name }}</strong>.</p>
<p><a class="email-button" href="{{ admin_url }}">Review request</a></p>
'''.strip(),
        variables=('request_type', 'game_name', 'requester_name', 'admin_url'),
        sample_context={
            'request_type': 'Game request',
            'game_name': 'Example Game: Deluxe Edition',
            'requester_name': 'Alex',
            'admin_url': 'https://games.example/admin/game-requests/42',
        },
    ),
    'request_status_update': EmailTemplateDefinition(
        key='request_status_update',
        name='Request status update',
        description='Sent to interested users when the status of their request changes.',
        icon='fa-bell',
        subject='Your game request is {{ status }}: {{ game_name }}',
        html='''
<h1>Request updated</h1>
<p>Hello {{ user_name }},</p>
<p>Your request for <strong>{{ game_name }}</strong> is now <strong>{{ status }}</strong>.</p>
{% if response %}<div class="email-note">{{ response }}</div>{% endif %}
{% if game_url %}<p><a class="email-button" href="{{ game_url }}">View available game</a></p>{% endif %}
'''.strip(),
        variables=('user_name', 'game_name', 'status', 'response', 'game_url'),
        sample_context={
            'user_name': 'Alex',
            'game_name': 'Example Game: Deluxe Edition',
            'status': 'Fulfilled',
            'response': 'The requested edition is now available in the library.',
            'game_url': 'https://games.example/game_details/sample-game',
        },
    ),
}


_environment = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)


def get_template_definition(template_key: str) -> EmailTemplateDefinition:
    try:
        return TEMPLATE_DEFINITIONS[template_key]
    except KeyError as error:
        raise ValueError('Unknown system email template.') from error


def _configured_template(template_key: str) -> SystemEmailTemplate | None:
    return db.session.get(SystemEmailTemplate, template_key)


def get_template_source(template_key: str) -> dict[str, object]:
    definition = get_template_definition(template_key)
    configured = _configured_template(template_key)
    return {
        'definition': definition,
        'subject': configured.subject_template if configured else definition.subject,
        'html': configured.html_template if configured else definition.html,
        'is_custom': configured is not None,
        'updated_at': configured.updated_at if configured else None,
        'updated_by': configured.updated_by if configured else None,
    }


def validate_template_source(template_key: str, subject: str, html: str) -> None:
    definition = get_template_definition(template_key)
    subject = subject.strip()
    html = html.strip()
    if not subject:
        raise ValueError('Subject is required.')
    if not html:
        raise ValueError('Email body is required.')
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise ValueError(f'Subject must be {MAX_SUBJECT_LENGTH} characters or fewer.')
    if len(html) > MAX_HTML_LENGTH:
        raise ValueError(f'Email body must be {MAX_HTML_LENGTH:,} characters or fewer.')
    if '\r' in subject or '\n' in subject:
        raise ValueError('Subject cannot contain line breaks.')

    allowed = set(GLOBAL_VARIABLES + definition.variables)
    for label, source in (('subject', subject), ('body', html)):
        try:
            parsed = _environment.parse(source)
        except Exception as error:
            raise ValueError(f'Invalid {label} template: {error}') from error
        unknown = sorted(meta.find_undeclared_variables(parsed) - allowed)
        if unknown:
            raise ValueError(f"Unknown variable{'s' if len(unknown) != 1 else ''} in {label}: {', '.join(unknown)}")


def save_template(template_key: str, subject: str, html: str, user_id: int | None) -> SystemEmailTemplate:
    validate_template_source(template_key, subject, html)
    record = _configured_template(template_key) or SystemEmailTemplate(template_key=template_key)
    record.subject_template = subject.strip()
    record.html_template = html.strip()
    record.updated_by_user_id = user_id
    db.session.add(record)
    db.session.commit()
    return record


def reset_template(template_key: str) -> None:
    get_template_definition(template_key)
    record = _configured_template(template_key)
    if record:
        db.session.delete(record)
        db.session.commit()


def _global_context() -> dict[str, str]:
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    values = settings.settings if settings and isinstance(settings.settings, dict) else {}
    return {
        'site_title': str(values.get('siteTitle') or 'Game Library'),
        'site_url': str((settings.site_url if settings else None) or 'http://127.0.0.1:5006').rstrip('/'),
    }


def _wrap_email(body: str, site_title: str) -> str:
    safe_title = escape(site_title)
    return f'''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{safe_title}</title></head>
<body style="margin:0;background:#0b0c14;color:#eef1ff;font-family:Arial,sans-serif;padding:24px">
  <div style="display:none;max-height:0;overflow:hidden;color:transparent">Message from {safe_title}</div>
  <main style="max-width:620px;margin:0 auto;border:1px solid #343958;border-radius:18px;background:#11131f;overflow:hidden">
    <header style="padding:22px 26px;border-bottom:1px solid #2a2e48;color:#9ab1ff;font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase">{safe_title}</header>
    <section style="padding:28px 26px;line-height:1.65">{body}</section>
    <footer style="padding:18px 26px;border-top:1px solid #2a2e48;color:#8e95aa;font-size:12px">This is an automated message from {safe_title}.</footer>
  </main>
  <style>.email-button{{display:inline-block;padding:11px 17px;border-radius:10px;background:#627aef;color:#fff!important;text-decoration:none;font-weight:700}}.email-muted{{color:#aeb4c8;font-size:13px}}.email-note{{padding:12px 14px;border-left:3px solid #7f96ff;background:#191c2d;border-radius:8px}}</style>
</body></html>'''


def render_system_email(template_key: str, context: dict[str, object] | None = None) -> tuple[str, str]:
    source = get_template_source(template_key)
    values: dict[str, object] = _global_context()
    values.update(context or {})
    validate_template_source(template_key, str(source['subject']), str(source['html']))
    try:
        subject = _environment.from_string(str(source['subject'])).render(values).strip()
        body = _environment.from_string(str(source['html'])).render(values)
    except Exception as error:
        raise ValueError(f'Unable to render system email template: {error}') from error
    if not subject or '\r' in subject or '\n' in subject:
        raise ValueError('Rendered email subject is invalid.')
    return subject, _wrap_email(body, str(values['site_title']))


def render_preview(template_key: str, subject: str, html: str) -> tuple[str, str]:
    definition = get_template_definition(template_key)
    validate_template_source(template_key, subject, html)
    values: dict[str, object] = {'site_title': 'GameStack', 'site_url': 'https://games.example'}
    values.update(definition.sample_context)
    try:
        rendered_subject = _environment.from_string(subject).render(values).strip()
        rendered_body = _environment.from_string(html).render(values)
    except Exception as error:
        raise ValueError(f'Unable to render preview: {error}') from error
    return rendered_subject, _wrap_email(rendered_body, str(values['site_title']))
