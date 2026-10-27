import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from sharewarez.utils import web_push


@pytest.mark.parametrize('existing_key', [False, True])
@pytest.mark.parametrize('status', [201, 404, 410, 500])
def test_push_signs_with_stored_pem(monkeypatch, existing_key, status):
    """Exercise real pywebpush key parsing/signing; only the network is mocked."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_key = base64.urlsafe_b64encode(private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )).rstrip(b'=').decode()
    settings = SimpleNamespace(
        vapid_private_key=pem if existing_key else None,
        vapid_public_key=public_key if existing_key else None,
        site_url='https://library.example.com',
    )
    subscriptions = [SimpleNamespace(
        user_id=1, endpoint=f'https://push.example.com/{index}', p256dh='unused', auth='unused',
    ) for index in range(2)]
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = subscriptions
    session.execute.return_value.scalars.return_value.first.return_value = settings
    monkeypatch.setattr(web_push, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr('pywebpush.WebPusher.__init__', lambda self, *args, **kwargs: None)
    send = MagicMock(return_value=SimpleNamespace(
        status_code=status, reason='test response', text='',
    ))
    monkeypatch.setattr('pywebpush.WebPusher.send', send)
    log = MagicMock()
    monkeypatch.setattr(web_push, 'log_system_event', log)

    delivered = web_push.send_push_notifications([1], 'New game', 'Available', '/library')

    assert delivered == (2 if status == 201 else 0)
    assert send.call_count == 2
    for call in send.call_args_list:
        assert json.loads(call.args[0]) == {
            'title': 'New game', 'message': 'Available', 'url': '/library',
        }
        authorization = call.args[1]['Authorization']
        assert authorization.startswith('vapid t=')
        assert authorization.endswith(f',k={settings.vapid_public_key}')
        assert call.kwargs['timeout'] == 10
    if existing_key:
        assert settings.vapid_private_key == pem
        assert settings.vapid_public_key == public_key
    else:
        assert settings.vapid_private_key.startswith('-----BEGIN PRIVATE KEY-----')
    assert session.delete.call_count == (2 if status in {404, 410} else 0)
    assert log.call_count == (2 if status == 500 else 0)
    session.commit.assert_called()


def test_push_without_subscriptions_does_not_load_keys(monkeypatch):
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    monkeypatch.setattr(web_push, 'db', SimpleNamespace(session=session))
    keys = MagicMock()
    monkeypatch.setattr(web_push, 'get_or_create_vapid_keys', keys)

    assert web_push.send_push_notifications([1], 'New game', 'Available') == 0
    keys.assert_not_called()
