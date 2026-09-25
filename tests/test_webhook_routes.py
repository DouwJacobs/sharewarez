from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select, text

from sharewarez.models import BackgroundJob, User, WebhookDelivery, WebhookEndpoint


def make_admin(db_session):
    suffix = uuid4().hex[:8]
    admin = User(
        name=f'webhook_admin_{suffix}', email=f'webhook_admin_{suffix}@example.com',
        password_hash='hash', role='admin',
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


@patch(
    'sharewarez.routes_admin_ext.webhooks.validate_webhook_url',
    return_value='https://example.com/hooks/sharewarez',
)
def test_admin_webhook_lifecycle(validate, client, db_session):
    admin = make_admin(db_session)
    login(client, admin)
    name = f'Lifecycle {uuid4()}'

    response = client.post('/admin/integrations/webhooks', json={
        'name': name,
        'url': 'https://example.com/hooks/sharewarez',
        'events': ['new_game'],
        'enabled': True,
    })
    assert response.status_code == 201
    created = response.get_json()
    assert created['secret']
    endpoint = db_session.get(WebhookEndpoint, created['id'])
    assert endpoint.url == 'https://example.com/hooks/sharewarez'
    raw = db_session.execute(text(
        'SELECT url, signing_secret FROM webhook_endpoints WHERE id = :id'
    ), {'id': endpoint.id}).mappings().one()
    assert raw['url'] != endpoint.url
    assert raw['signing_secret'] != created['secret']

    response = client.post(f'/admin/integrations/webhooks/{endpoint.id}', json={
        'name': f'{name} updated', 'url': '', 'events': ['request_updated'],
        'enabled': False,
    })
    assert response.status_code == 200
    db_session.refresh(endpoint)
    assert endpoint.url == 'https://example.com/hooks/sharewarez'
    assert endpoint.subscribed_events == ['request_updated']
    assert endpoint.is_enabled is False

    previous_secret = endpoint.signing_secret
    response = client.post(f'/admin/integrations/webhooks/{endpoint.id}/rotate-secret')
    assert response.status_code == 200
    assert response.get_json()['secret'] != previous_secret

    response = client.post(f'/admin/integrations/webhooks/{endpoint.id}/delete')
    assert response.status_code == 200
    assert db_session.get(WebhookEndpoint, endpoint.id) is None
    assert validate.call_count == 1


def test_webhook_test_and_retry_are_queued(client, db_session):
    admin = make_admin(db_session)
    login(client, admin)
    endpoint = WebhookEndpoint(
        name=f'Queue {uuid4()}', url='https://example.com/hook',
        signing_secret='secret', subscribed_events=['new_game'], is_enabled=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(f'/admin/integrations/webhooks/{endpoint.id}/test')
    assert response.status_code == 200
    delivery = db_session.execute(select(WebhookDelivery).where(
        WebhookDelivery.endpoint_id == endpoint.id,
    )).scalar_one()
    assert delivery.event.is_test is True
    jobs = db_session.execute(select(BackgroundJob).where(
        BackgroundJob.task_name == 'notifications.send_webhook',
    )).scalars()
    assert any(job.payload.get('delivery_id') == delivery.id for job in jobs)

    delivery.status = 'failed'
    db_session.commit()
    response = client.post(f'/admin/integrations/webhook-deliveries/{delivery.id}/retry')
    assert response.status_code == 200
    db_session.refresh(delivery)
    assert delivery.status == 'queued'


def test_webhook_routes_require_admin(client, db_session):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'webhook_user_{suffix}', email=f'webhook_user_{suffix}@example.com',
        password_hash='hash', role='user',
    )
    db_session.add(user)
    db_session.commit()
    login(client, user)

    response = client.post('/admin/integrations/webhooks', json={
        'name': 'Denied', 'url': 'https://example.com/hook', 'events': ['new_game'],
    })
    assert response.status_code in {302, 403}
