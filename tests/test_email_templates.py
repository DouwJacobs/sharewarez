from pathlib import Path

import pytest

from sharewarez.utils.email_templates import (
    TEMPLATE_DEFINITIONS,
    render_preview,
    render_system_email,
    validate_template_source,
)


ROOT = Path(__file__).resolve().parents[1]


def test_five_system_email_templates_are_defined():
    assert set(TEMPLATE_DEFINITIONS) == {
        'account_confirmation',
        'password_reset',
        'user_invitation',
        'admin_new_request',
        'request_status_update',
    }


@pytest.mark.parametrize('template_key', TEMPLATE_DEFINITIONS)
def test_default_system_email_templates_render_preview(template_key):
    definition = TEMPLATE_DEFINITIONS[template_key]
    subject, html = render_preview(template_key, definition.subject, definition.html)

    assert subject
    assert '<!doctype html>' in html
    assert 'GameStack' in html
    assert '{{' not in subject


def test_template_validation_rejects_unknown_variables_and_header_injection():
    with pytest.raises(ValueError, match='Unknown variable'):
        validate_template_source('password_reset', 'Hello {{ secret }}', '<p>Body</p>')
    with pytest.raises(ValueError, match='line breaks'):
        validate_template_source('password_reset', 'Hello\nBcc: attacker@example.com', '<p>Body</p>')


def test_sandbox_blocks_unsafe_attribute_access():
    with pytest.raises(ValueError, match='Unable to render preview'):
        render_preview('password_reset', 'Safe subject', "{{ ''.__class__.__mro__ }}")


def test_runtime_context_is_html_escaped(monkeypatch):
    monkeypatch.setattr(
        'sharewarez.utils.email_templates.get_template_source',
        lambda key: {'subject': 'Hello {{ user_name }}', 'html': '<p>{{ user_name }}</p>'},
    )
    monkeypatch.setattr(
        'sharewarez.utils.email_templates._global_context',
        lambda: {'site_title': 'GameStack', 'site_url': 'https://games.example'},
    )

    subject, html = render_system_email('password_reset', {
        'user_name': '<script>alert(1)</script>',
        'reset_url': 'https://games.example/reset',
        'expires_in': '15 minutes',
    })

    assert '<script>' not in subject
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_admin_email_template_ui_and_routes_are_registered():
    route = (ROOT / 'sharewarez/routes_admin_ext/email_templates.py').read_text(encoding='utf-8')
    template = (ROOT / 'sharewarez/templates/admin/admin_email_templates.html').read_text(encoding='utf-8')
    dashboard = (ROOT / 'sharewarez/templates/admin/admin_dashboard.html').read_text(encoding='utf-8')

    assert "@admin2_bp.route('/admin/email-templates'" in route
    assert "@admin2_bp.post('/admin/email-templates/<template_key>/preview')" in route
    assert "@admin2_bp.post('/admin/email-templates/<template_key>/reset')" in route
    assert 'emailTemplatePreviewFrame' in template
    assert 'email-variable-chip' in template
    assert "url_for('admin2.email_templates')" in dashboard


def test_all_transactional_email_paths_use_managed_renderer():
    smtp = (ROOT / 'sharewarez/utils/smtp.py').read_text(encoding='utf-8')
    login = (ROOT / 'sharewarez/routes_login.py').read_text(encoding='utf-8')
    requests = (ROOT / 'sharewarez/utils/request_notifications.py').read_text(encoding='utf-8')

    assert "render_system_email('password_reset'" in smtp
    assert "render_system_email('user_invitation'" in smtp
    assert "render_system_email('account_confirmation'" in login
    assert "render_system_email('admin_new_request'" in requests
    assert "render_system_email('request_status_update'" in requests
