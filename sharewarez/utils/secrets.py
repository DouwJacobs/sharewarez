"""Authenticated encryption for long-lived integration credentials."""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, has_app_context
from sqlalchemy.types import Text, TypeDecorator


_PREFIX = 'enc:v1:'


def _configured_key_material():
    if has_app_context():
        configured = current_app.config.get('CREDENTIAL_ENCRYPTION_KEY')
        fallback = current_app.config.get('SECRET_KEY')
    else:
        configured = os.getenv('CREDENTIAL_ENCRYPTION_KEY')
        fallback = os.getenv('SECRET_KEY')
    material = configured or fallback
    if not material:
        raise RuntimeError('Credential encryption requires CREDENTIAL_ENCRYPTION_KEY or SECRET_KEY')
    return material


def _fernet(material=None):
    material = material or _configured_key_material()
    key = base64.urlsafe_b64encode(hashlib.sha256(str(material).encode('utf-8')).digest())
    return Fernet(key)


def encrypt_secret(value, key_material=None):
    if value is None or value == '' or value.startswith(_PREFIX):
        return value
    token = _fernet(key_material).encrypt(value.encode('utf-8')).decode('ascii')
    return f'{_PREFIX}{token}'


def decrypt_secret(value, key_material=None):
    if value is None or value == '' or not value.startswith(_PREFIX):
        return value
    try:
        return _fernet(key_material).decrypt(
            value[len(_PREFIX):].encode('ascii')
        ).decode('utf-8')
    except InvalidToken as exc:
        raise RuntimeError('Stored integration credential cannot be decrypted') from exc


class EncryptedString(TypeDecorator):
    """Text column that exposes plaintext while persisting Fernet ciphertext."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        return decrypt_secret(value)
