from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import (
    GlobalSettings, Notification, NotificationEvent, User, WebhookDelivery, WebhookEndpoint,
)
from sharewarez.utils.notification_events import personal_preferences, publish_event
from sharewarez.utils.outbound_webhooks import deliver_webhook, sign_payload, validate_webhook_url
from sharewarez.utils.user_preferences import update_experience_settings


def set_policy(db_session, event_type, **channels):
    settings = db_session.execute(select(GlobalSettings)).scalars().first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db_session.add(settings)
    values = dict(settings.settings or {})
    policy = dict(values.get('notificationPolicy') or {})
    policy[event_type] = {
        'in_app': False, 'email': False, 'push': False, 'discord': False,
        **channels,
    }
    values['notificationPolicy'] = policy
    settings.settings = values
    db_session.commit()


@pytest.fixture
def delivery_user(db_session):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'delivery_{suffix}', email=f'delivery_{suffix}@example.com',
        password_hash='hash', role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(autouse=True)
def clean_webhook_endpoints(db_session):
    db_session.query(WebhookDelivery).delete(synchronize_session=False)
    db_session.query(WebhookEndpoint).delete(synchronize_session=False)
    db_session.commit()
    yield
    db_session.rollback()
    db_session.query(WebhookDelivery).delete(synchronize_session=False)
    db_session.query(WebhookEndpoint).delete(synchronize_session=False)
    db_session.commit()


@patch('sharewarez.utils.notification_events.enqueue')
def test_publish_event_fans_out_once(mock_enqueue, db_session, delivery_user):
    set_policy(db_session, 'new_game', in_app=True, email=True, push=True)
    endpoint = WebhookEndpoint(
        name=f'Automation {uuid4()}', url='https://example.com/hooks/sharewarez',
        signing_secret='secret', subscribed_events=['new_game'],
    )
    db_session.add(endpoint)
    db_session.commit()

    dedupe_key = f'new-game:{uuid4()}'
    event = publish_event(
        [delivery_user.id], 'new_game', 'New game', 'A game arrived.',
        link_url='/game_details/example', dedupe_key=dedupe_key,
        resource_type='game', resource_id='example', event_data={'library': 'Games'},
    )
    duplicate = publish_event(
        [delivery_user.id], 'new_game', 'New game', 'A game arrived.',
        link_url='/game_details/example', dedupe_key=dedupe_key,
    )

    assert duplicate.id == event.id
    notification = db_session.execute(select(Notification).where(
        Notification.event_id == event.id, Notification.user_id == delivery_user.id,
    )).scalar_one()
    assert notification.title == 'New game'
    delivery = db_session.execute(select(WebhookDelivery).where(
        WebhookDelivery.event_id == event.id,
    )).scalar_one()
    assert delivery.payload['subject'] == {'type': 'game', 'id': 'example'}
    assert delivery.payload['data']['library'] == 'Games'
    task_names = [call.args[0] for call in mock_enqueue.call_args_list]
    assert task_names.count('notifications.send_email') == 1
    assert task_names.count('notifications.send_push') == 1
    assert task_names.count('notifications.send_webhook') == 1


@patch('sharewarez.utils.notification_events.enqueue')
def test_personal_event_override_suppresses_personal_channels(mock_enqueue, db_session, delivery_user):
    set_policy(db_session, 'new_game', in_app=True, email=True, push=True)
    update_experience_settings(delivery_user, notifications={
        'version': 2,
        'events': {'new_game': {'in_app': False, 'email': False, 'push': False}},
    })
    db_session.commit()

    key = f'hidden:{uuid4()}'
    publish_event([delivery_user.id], 'new_game', 'Hidden', 'No personal delivery.', dedupe_key=key)

    assert personal_preferences(delivery_user)['new_game'] == {
        'in_app': False, 'email': False, 'push': False,
    }
    assert db_session.execute(select(Notification).where(
        Notification.user_id == delivery_user.id, Notification.dedupe_key == key,
    )).scalar_one_or_none() is None
    assert not mock_enqueue.called


def test_webhook_signature_is_stable():
    assert sign_payload('secret', '123', b'{"ok":true}') == (
        'sha256=12f14ade5e7e737164d9ae20ea4e070056a3045b2c8f42f5f216008eae4684dd'
    )


def test_webhook_payload_uses_privacy_safe_message(db_session):
    from sharewarez.utils.notification_events import _payload

    event = NotificationEvent(
        event_type='issue_comment', title='Issue reply', message='Private comment body',
        event_data={'_webhook_message': 'A public issue reply was added.', 'status': 'open'},
    )
    db_session.add(event)
    db_session.flush()
    payload = _payload(event)
    assert payload['data']['message'] == 'A public issue reply was added.'
    assert payload['data']['status'] == 'open'
    assert '_webhook_message' not in payload['data']


def test_webhook_url_blocks_private_targets(monkeypatch):
    monkeypatch.delenv('ALLOW_PRIVATE_WEBHOOK_TARGETS', raising=False)
    monkeypatch.setattr('socket.getaddrinfo', lambda *_args, **_kwargs: [
        (2, 1, 6, '', ('127.0.0.1', 443)),
    ])
    with pytest.raises(ValueError, match='public addresses'):
        validate_webhook_url('https://localhost/hook')


def test_webhook_delivery_records_target_validation_failure(monkeypatch, db_session):
    monkeypatch.delenv('ALLOW_PRIVATE_WEBHOOK_TARGETS', raising=False)
    monkeypatch.setattr('socket.getaddrinfo', lambda *_args, **_kwargs: [
        (2, 1, 6, '', ('127.0.0.1', 443)),
    ])
    endpoint = WebhookEndpoint(
        name=f'Private receiver {uuid4()}', url='https://localhost/hook',
        signing_secret='secret', subscribed_events=['new_game'],
    )
    event = NotificationEvent(
        event_type='new_game', title='New game', message='Available', event_data={},
    )
    db_session.add_all([endpoint, event])
    db_session.flush()
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id, event_id=event.id,
        payload={'version': 1, 'id': event.id, 'type': 'new_game'},
    )
    db_session.add(delivery)
    db_session.commit()

    result = deliver_webhook(delivery.id, final_attempt=True)

    assert result == {
        'delivered': False, 'error': 'Webhook target validation failed.',
    }
    assert delivery.status == 'failed'
    assert delivery.attempts == 1
    assert delivery.error_message == 'Webhook target validation failed.'


@patch('sharewarez.utils.outbound_webhooks.requests.post')
def test_webhook_delivery_uses_signed_snapshot(mock_post, monkeypatch, db_session):
    monkeypatch.setenv('ALLOW_PRIVATE_WEBHOOK_TARGETS', 'true')
    mock_post.return_value = SimpleNamespace(status_code=204, text='')
    endpoint = WebhookEndpoint(
        name=f'Receiver {uuid4()}', url='https://127.0.0.1/hook', signing_secret='secret',
        subscribed_events=['new_game'],
    )
    event = NotificationEvent(
        event_type='new_game', title='New game', message='Available', event_data={},
    )
    db_session.add_all([endpoint, event])
    db_session.flush()
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id, event_id=event.id,
        payload={'version': 1, 'id': event.id, 'type': 'new_game'},
    )
    db_session.add(delivery)
    db_session.commit()

    result = deliver_webhook(delivery.id)

    assert result == {'delivered': True, 'status_code': 204}
    assert delivery.status == 'delivered'
    headers = mock_post.call_args.kwargs['headers']
    assert headers['X-Sharewarez-Delivery'] == delivery.id
    assert headers['X-Sharewarez-Signature'].startswith('sha256=')
    assert mock_post.call_args.kwargs['allow_redirects'] is False
