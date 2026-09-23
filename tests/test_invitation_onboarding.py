import re
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from sharewarez import db
from sharewarez.models import InviteToken, User
from sharewarez.utils.invitations import (
    digest_invitation_credential,
    invitation_status,
    utc_now,
)


@pytest.fixture(autouse=True)
def clean_invitation_data(db_session):
    db_session.execute(text('TRUNCATE TABLE invite_tokens RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE users RESTART IDENTITY CASCADE'))
    db_session.commit()


@pytest.fixture
def admin(db_session):
    user = User(
        name='invite_admin',
        email='invite-admin@example.com',
        role='admin',
        state=True,
        is_email_verified=True,
        user_id=str(uuid4()),
    )
    user.set_password('admin-test-password')
    db_session.add(user)
    db_session.commit()
    return user


def sign_in(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def make_invitation(db_session, creator, raw_token='claim-this-invitation', **values):
    invitation = InviteToken(
        token_digest=digest_invitation_credential(raw_token),
        creator_user_id=creator.user_id,
        **values,
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


def test_admin_creates_one_time_share_link_without_storing_raw_token(client, db_session, admin):
    sign_in(client, admin)
    response = client.post('/admin/invitations', data={
        'email': '',
        'expires_days': '7',
        'delivery': 'link',
    })

    assert response.status_code == 201
    match = re.search(rb'http[^<]+/join/([A-Za-z0-9_-]+)', response.data)
    assert match
    raw_token = match.group(1).decode()
    invitation = db_session.scalar(select(InviteToken))
    assert invitation.recipient_email is None
    assert invitation.token_digest == digest_invitation_credential(raw_token)
    assert raw_token not in invitation.token_digest
    assert invitation_status(invitation) == 'pending'


def test_admin_sends_email_bound_invitation(client, db_session, admin):
    sign_in(client, admin)
    with patch('sharewarez.routes_admin_ext.invites.send_invite_email', return_value=True) as send:
        response = client.post('/admin/invitations', data={
            'email': 'New.Person@Example.com',
            'expires_days': '5',
            'delivery': 'email',
        })

    assert response.status_code == 302
    invitation = db_session.scalar(select(InviteToken))
    assert invitation.recipient_email == 'new.person@example.com'
    assert send.call_args.args[0] == 'new.person@example.com'
    assert '/join/' in send.call_args.args[1]


def test_invitee_chooses_credentials_and_consumes_invitation(client, db_session, admin):
    raw_token = 'choose-your-own-credentials'
    invitation = make_invitation(db_session, admin, raw_token)
    with patch('sharewarez.routes_login.send_email', return_value=True):
        response = client.post(f'/join/{raw_token}', data={
            'username': 'new.member',
            'email': 'NEW.MEMBER@example.com',
            'password': 'member-test-password',
            'confirm_password': 'member-test-password',
        })

    assert response.status_code == 200
    assert b'Check your email' in response.data
    user = db_session.scalar(select(User).where(User.name == 'new.member'))
    assert user.email == 'new.member@example.com'
    assert user.role == 'user'
    assert user.state is True
    assert user.is_email_verified is False
    assert user.check_password('member-test-password')
    db_session.refresh(invitation)
    assert invitation.used is True
    assert invitation.used_by == user.user_id
    assert invitation.used_at is not None


def test_email_bound_invitation_rejects_a_different_address(client, db_session, admin):
    raw_token = 'email-bound-invitation'
    make_invitation(
        db_session,
        admin,
        raw_token,
        recipient_email='reserved@example.com',
    )
    response = client.post(f'/join/{raw_token}', data={
        'username': 'wrong.person',
        'email': 'different@example.com',
        'password': 'member-test-password',
        'confirm_password': 'member-test-password',
    })

    assert response.status_code == 200
    assert b'Use the email address this invitation was sent to.' in response.data
    assert db_session.scalar(select(User).where(User.name == 'wrong.person')) is None


@pytest.mark.parametrize('state', ['expired', 'revoked', 'accepted'])
def test_non_pending_invitation_has_one_generic_public_result(client, db_session, admin, state):
    raw_token = f'{state}-invitation'
    values = {}
    if state == 'expired':
        values['expires_at'] = utc_now() - timedelta(minutes=1)
    elif state == 'revoked':
        values['revoked_at'] = utc_now()
    else:
        values['used'] = True
        values['used_at'] = utc_now()
    make_invitation(db_session, admin, raw_token, **values)

    response = client.get(f'/join/{raw_token}')
    assert response.status_code == 400
    assert b'This invitation is no longer available' in response.data


def test_admin_can_revoke_and_replace_without_recovering_old_credential(client, db_session, admin):
    raw_token = 'replace-this-invitation'
    original = make_invitation(db_session, admin, raw_token)
    sign_in(client, admin)

    response = client.post(f'/admin/invitations/{original.id}/replace', data={'delivery': 'link'})
    assert response.status_code == 201
    db_session.refresh(original)
    assert original.revoked_at is not None
    invitations = db_session.scalars(select(InviteToken).order_by(InviteToken.id)).all()
    assert len(invitations) == 2
    assert invitations[1].token_digest != original.token_digest
    assert raw_token.encode() not in response.data


def test_expired_and_revoked_invitations_do_not_consume_allowance(client, db_session, admin):
    admin.invite_quota = 2
    make_invitation(db_session, admin, 'active')
    make_invitation(db_session, admin, 'expired', expires_at=utc_now() - timedelta(days=1))
    make_invitation(db_session, admin, 'revoked', revoked_at=utc_now())
    sign_in(client, admin)

    response = client.get('/admin/manage_invites')
    assert response.status_code == 200
    assert b'1 of 2 available' in response.data
