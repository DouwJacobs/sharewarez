"""Validation, signing, and delivery for generic outbound webhooks."""

from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
import socket
from urllib.parse import urlparse

import requests

from sharewarez import db
from sharewarez.models import WebhookDelivery


RETRYABLE_STATUS = {408, 425, 429}


def validate_webhook_url(value):
    value = str(value or '').strip()
    if not value or len(value) > 2048:
        raise ValueError('Webhook URL is required and must not exceed 2048 characters.')
    parsed = urlparse(value)
    allow_private = os.getenv('ALLOW_PRIVATE_WEBHOOK_TARGETS', 'false').lower() == 'true'
    allowed_schemes = {'http', 'https'} if allow_private else {'https'}
    if parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Webhook URL must be an HTTPS URL without embedded credentials.')
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise ValueError('Webhook hostname could not be resolved.') from error
    if not allow_private:
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError('Webhook target must resolve only to public addresses.')
    return value


def sign_payload(secret, timestamp, body):
    material = f'{timestamp}.'.encode() + body
    return 'sha256=' + hmac.new(secret.encode(), material, hashlib.sha256).hexdigest()


def deliver_webhook(delivery_id, *, final_attempt=False):
    delivery = db.session.get(WebhookDelivery, delivery_id)
    if delivery is None:
        return {'delivered': False, 'status': 'removed'}
    endpoint = delivery.endpoint
    if not endpoint.is_enabled:
        delivery.status = 'cancelled'
        delivery.error_message = 'Endpoint is disabled.'
        db.session.commit()
        return {'delivered': False, 'status': 'cancelled'}
    delivery.attempts += 1
    try:
        url = validate_webhook_url(endpoint.url)
    except ValueError as error:
        delivery.status = 'failed' if final_attempt else 'retrying'
        delivery.error_message = 'Webhook target validation failed.'
        db.session.commit()
        if not final_attempt:
            raise RuntimeError('Webhook target validation failed') from error
        return {'delivered': False, 'error': delivery.error_message}
    body = json.dumps(delivery.payload, separators=(',', ':'), sort_keys=True).encode()
    if len(body) > 65536:
        delivery.status = 'failed'
        delivery.error_message = 'Webhook payload exceeds 64 KiB.'
        db.session.commit()
        return {'delivered': False, 'status': 'failed'}
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    try:
        response = requests.post(
            url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Sharewarez-Webhook/1',
                'X-Sharewarez-Delivery': delivery.id,
                'X-Sharewarez-Event': delivery.event.event_type,
                'X-Sharewarez-Timestamp': timestamp,
                'X-Sharewarez-Signature': sign_payload(endpoint.signing_secret, timestamp, body),
            },
            timeout=10,
            allow_redirects=False,
        )
        delivery.response_status = response.status_code
        delivery.response_excerpt = ''.join(
            character if character.isprintable() else ' '
            for character in response.text[:2048]
        )
        if 200 <= response.status_code < 300:
            delivery.status = 'delivered'
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.error_message = None
            db.session.commit()
            return {'delivered': True, 'status_code': response.status_code}
        retryable = response.status_code in RETRYABLE_STATUS or response.status_code >= 500
        delivery.status = 'failed' if final_attempt or not retryable else 'retrying'
        delivery.error_message = f'HTTP {response.status_code}'
        db.session.commit()
        if retryable and not final_attempt:
            raise RuntimeError(f'Webhook returned HTTP {response.status_code}')
        return {'delivered': False, 'status_code': response.status_code}
    except requests.RequestException as error:
        delivery.status = 'failed' if final_attempt else 'retrying'
        delivery.error_message = f'{type(error).__name__}: outbound request failed'
        db.session.commit()
        if not final_attempt:
            raise RuntimeError('Webhook request failed') from error
        return {'delivered': False, 'error': delivery.error_message}
