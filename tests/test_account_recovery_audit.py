from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select, func
from sharewarez.models import User, InviteToken
from sharewarez.routes_login import get_serializer


def make_user(session, **values):
    key = uuid4().hex
    user = User(name=key, email=key + '@example.com', state=True, role="user", **values)
    user.set_password('original-test-password')
    session.add(user)
    session.commit()
    return user


@pytest.mark.parametrize('minutes,missing,valid', [(1, False, True), (16, False, False), (1, True, False)])
def test_reset_committed_timestamp_and_single_use(client, db_session, minutes, missing, valid):
    user = make_user(db_session)
    token = uuid4().hex
    user.password_reset_token = token
    user.token_creation_time = None if missing else datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db_session.commit()
    db_session.expire_all()
    response = client.get('/reset_password/' + token)
    assert response.status_code == (200 if valid else 302)
    if valid:
        response = client.post('/reset_password/' + token, data={'password': 'new-test-password', 'confirm_password': 'new-test-password'})
        assert response.status_code == 302
        db_session.refresh(user)
        assert user.check_password('new-test-password')
        assert user.password_reset_token is None
        assert client.get('/reset_password/' + token).status_code == 302


def test_mixed_case_confirmation_and_invalid_link(client, db_session):
    user = make_user(db_session, is_email_verified=False)
    token = get_serializer().dumps(user.email.upper(), salt='email-confirm')
    assert client.get('/confirm/' + token).status_code == 200
    db_session.refresh(user)
    assert user.is_email_verified
    invalid = client.get('/confirm/invalid')
    assert invalid.status_code == 400
    assert b'/request_new_activation' in invalid.data


@pytest.mark.parametrize('path', ['/reset_password_request', '/request_new_activation'])
def test_public_mail_response_independent_of_account(client, db_session, path):
    user = make_user(db_session, is_email_verified=False)
    with patch('sharewarez.utils.smtp.get_smtp_settings', return_value=None):
        known = client.post(path, data={'email': user.email}, follow_redirects=True)
        unknown = client.post(path, data={'email': uuid4().hex + '@example.com'}, follow_redirects=True)
    for response in [known, unknown]:
        assert response.status_code == 200
        assert b'SMTP settings not configured' not in response.data
    with client.session_transaction() as session:
        assert not session.get('_flashes')
    assert b'If an account' in known.data and b'If an account' in unknown.data


def test_concurrent_invitation_consumed_once_without_mail(app, db_session):
    creator = make_user(db_session)
    token = uuid4().hex
    invite = InviteToken(token=token, creator_user_id=creator.user_id)
    db_session.add(invite)
    db_session.commit()
    names = [uuid4().hex, uuid4().hex]
    def register(name):
        with app.test_client() as client:
            return client.post('/register?token=' + token, data={'username': name, 'email': name + '@example.com', 'password': 'new-test-password'}).status_code
    with patch('sharewarez.routes_login.send_email', return_value=False), ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(register, names)) == [302, 302]
    db_session.expire_all()
    assert db_session.scalar(select(func.count(User.id)).where(User.name.in_(names))) == 1
    db_session.refresh(invite)
    assert invite.used and invite.used_by and invite.used_at