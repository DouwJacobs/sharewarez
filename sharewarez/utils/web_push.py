"""Minimal self-hosted Web Push delivery."""

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import GlobalSettings, PushSubscription
from sharewarez.utils.event_logging import log_system_event


def get_or_create_vapid_keys():
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db.session.add(settings)
    if settings.vapid_private_key and settings.vapid_public_key:
        return settings.vapid_private_key, settings.vapid_public_key

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    settings.vapid_private_key = private_pem
    settings.vapid_public_key = base64.urlsafe_b64encode(public_bytes).rstrip(b'=').decode()
    db.session.commit()
    return private_pem, settings.vapid_public_key


def send_push_notifications(user_ids, title, message, link_url=None):
    subscriptions = db.session.execute(
        select(PushSubscription).where(PushSubscription.user_id.in_(set(user_ids)))
    ).scalars().all()
    if not subscriptions:
        return 0
    private_key, _ = get_or_create_vapid_keys()
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    subject = (settings.site_url or '').strip() if settings else ''
    if not subject.startswith('https://'):
        sender = (settings.smtp_default_sender or 'admin@localhost') if settings else 'admin@localhost'
        subject = f'mailto:{sender}'
    payload = json.dumps({'title': title, 'message': message, 'url': link_url or '/notifications'})
    delivered = 0
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={'sub': subject},
                timeout=10,
            )
            delivered += 1
        except WebPushException as error:
            status = getattr(error.response, 'status_code', None)
            if status in {404, 410}:
                db.session.delete(subscription)
            else:
                log_system_event(
                    f'Web Push delivery failed with status {status or "unknown"}',
                    event_type='notification', event_level='warning', audit_user='system',
                )
    db.session.commit()
    return delivered
