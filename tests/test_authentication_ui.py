from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LOGIN_TEMPLATES = ROOT / 'sharewarez' / 'templates' / 'login'
AUTH_CSS = (
    ROOT / 'sharewarez' / 'setup' / 'default_theme' / 'css' / 'login' / 'authentication.css'
)


@pytest.mark.parametrize(
    ('path', 'heading'),
    [
        ('/login', b'Welcome back'),
        ('/register', b'Create your account'),
        ('/reset_password_request', b'Reset your password'),
        ('/request_new_activation', b'Request an activation link'),
    ],
)
def test_public_account_entry_points_share_the_modern_auth_shell(client, path, heading):
    response = client.get(path)

    assert response.status_code == 200
    assert heading in response.data
    assert b'css/login/authentication.css' in response.data
    assert response.data.count(b'class="app-surface auth-shell') == 1
    assert b'class="auth-brand"' in response.data
    assert b'class="auth-main"' in response.data


def test_auth_templates_do_not_restore_legacy_page_layouts():
    templates = [
        'login.html',
        'registration.html',
        'reset_password_request.html',
        'reset_password.html',
        'request_new_activation.html',
        'confirmation_expired.html',
        'confirmation_invalid.html',
        'confirmation_success.html',
        'registration_already_confirmed.html',
        'accept_invitation.html',
        'invitation_complete.html',
        'invitation_invalid.html',
    ]

    for template_name in templates:
        markup = (LOGIN_TEMPLATES / template_name).read_text(encoding='utf-8')
        assert "partials/auth_layout.html" in markup, template_name
        assert 'css/login/authentication.css' in markup, template_name
        assert 'container-login' not in markup, template_name
        assert 'style="' not in markup, template_name
        assert '<i ' not in markup, template_name


def test_auth_shell_preserves_shared_surface_and_mobile_control_contracts():
    stylesheet = AUTH_CSS.read_text(encoding='utf-8')
    layout = (
        ROOT / 'sharewarez' / 'templates' / 'partials' / 'auth_layout.html'
    ).read_text(encoding='utf-8')

    assert layout.count('app-surface') == 1
    assert '<i ' not in layout
    assert '{{ brand_title }}' in layout
    assert '{{ brand_description }}' in layout
    assert '@media (max-width: 760px)' in stylesheet
    assert '.auth-shell { grid-template-columns: 1fr; }' in stylesheet
    assert 'flex-basis: var(--app-control-height)' in stylesheet
    assert 'width: min(1060px, 100%)' in stylesheet
