"""Administrator routes for generic outbound webhooks."""

from datetime import datetime, timezone
import secrets

from flask import jsonify, request
from flask_login import login_required
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sharewarez import db
from sharewarez.models import WebhookDelivery, WebhookEndpoint
from sharewarez.utils.auth import admin_required
from sharewarez.utils.background_jobs import enqueue
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.notification_events import event_catalog, publish_event
from sharewarez.utils.outbound_webhooks import validate_webhook_url
from . import admin2_bp


def _endpoint(endpoint_id):
    return db.get_or_404(WebhookEndpoint, endpoint_id)


def _events(payload):
    values = payload.get('events') or []
    if not isinstance(values, list) or not values or set(values) - set(event_catalog()):
        raise ValueError('Select at least one valid event.')
    return sorted(set(values))


@admin2_bp.post('/admin/integrations/webhooks')
@login_required
@admin_required
def create_webhook_endpoint():
    payload = request.get_json(silent=True) or {}
    try:
        name = str(payload.get('name') or '').strip()
        if not name or len(name) > 100:
            raise ValueError('Webhook name is required and must not exceed 100 characters.')
        secret = secrets.token_urlsafe(32)
        endpoint = WebhookEndpoint(
            name=name, url=validate_webhook_url(payload.get('url')),
            signing_secret=secret, subscribed_events=_events(payload),
            is_enabled=bool(payload.get('enabled', True)),
        )
        db.session.add(endpoint)
        db.session.commit()
        log_system_event(f'Outbound webhook endpoint created: {endpoint.id}', event_type='audit')
        return jsonify({'message': 'Webhook created.', 'id': endpoint.id, 'secret': secret}), 201
    except ValueError as error:
        db.session.rollback()
        return jsonify({'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A webhook with this name already exists.'}), 409


@admin2_bp.post('/admin/integrations/webhooks/<endpoint_id>')
@login_required
@admin_required
def update_webhook_endpoint(endpoint_id):
    endpoint = _endpoint(endpoint_id)
    payload = request.get_json(silent=True) or {}
    try:
        name = str(payload.get('name') or '').strip()
        if not name or len(name) > 100:
            raise ValueError('Webhook name is required and must not exceed 100 characters.')
        endpoint.name = name
        if str(payload.get('url') or '').strip():
            endpoint.url = validate_webhook_url(payload['url'])
        endpoint.subscribed_events = _events(payload)
        endpoint.is_enabled = bool(payload.get('enabled'))
        endpoint.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        log_system_event(f'Outbound webhook endpoint updated: {endpoint.id}', event_type='audit')
        return jsonify({'message': 'Webhook updated.'})
    except ValueError as error:
        db.session.rollback()
        return jsonify({'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A webhook with this name already exists.'}), 409


@admin2_bp.post('/admin/integrations/webhooks/<endpoint_id>/rotate-secret')
@login_required
@admin_required
def rotate_webhook_secret(endpoint_id):
    endpoint = _endpoint(endpoint_id)
    secret = secrets.token_urlsafe(32)
    endpoint.signing_secret = secret
    endpoint.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    log_system_event(f'Outbound webhook secret rotated: {endpoint.id}', event_type='audit')
    return jsonify({'message': 'Signing secret rotated.', 'secret': secret})


@admin2_bp.post('/admin/integrations/webhooks/<endpoint_id>/test')
@login_required
@admin_required
def test_webhook_endpoint(endpoint_id):
    endpoint = _endpoint(endpoint_id)
    if not endpoint.is_enabled:
        return jsonify({'error': 'Enable this endpoint before sending a test.'}), 409
    event_type = (endpoint.subscribed_events or ['new_game'])[0]
    event = publish_event(
        [], event_type, 'Sharewarez webhook test',
        'This signed test confirms that outbound delivery is configured.',
        link_url='/admin/integrations', dedupe_key=None, is_test=True,
        endpoint_ids=[endpoint.id],
    )
    return jsonify({'message': 'Test delivery queued.', 'event_id': event.id})


@admin2_bp.post('/admin/integrations/webhooks/<endpoint_id>/delete')
@login_required
@admin_required
def delete_webhook_endpoint(endpoint_id):
    endpoint = _endpoint(endpoint_id)
    db.session.delete(endpoint)
    db.session.commit()
    log_system_event(f'Outbound webhook endpoint deleted: {endpoint_id}', event_type='audit')
    return jsonify({'message': 'Webhook deleted.'})


@admin2_bp.post('/admin/integrations/webhook-deliveries/<delivery_id>/retry')
@login_required
@admin_required
def retry_webhook_delivery(delivery_id):
    delivery = db.get_or_404(WebhookDelivery, delivery_id)
    if delivery.status not in {'failed', 'cancelled'}:
        return jsonify({'error': 'Only failed or cancelled deliveries can be retried.'}), 409
    delivery.status = 'queued'
    delivery.error_message = None
    enqueue(
        'notifications.send_webhook', {'delivery_id': delivery.id},
        max_attempts=5, created_by_id=None, commit=False,
    )
    db.session.commit()
    return jsonify({'message': 'Webhook retry queued.'})
