import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, g, jsonify, request
from sqlalchemy import select


API_TOKEN_SCOPES = {
    'profile:read': 'Read your account identity',
    'library:read': 'Read games and library metadata',
    'downloads:read': 'Read your download requests and transfer history',
}


def _token_digest(raw_token):
    key = current_app.config['SECRET_KEY'].encode('utf-8')
    return hmac.new(key, raw_token.encode('utf-8'), hashlib.sha256).hexdigest()


def create_api_token(user, name, scopes, expires_days=90):
    from sharewarez import db
    from sharewarez.models import ApiToken

    clean_name = (name or '').strip()
    if not clean_name or len(clean_name) > 80:
        raise ValueError('Token name must be between 1 and 80 characters')
    clean_scopes = sorted(set(scopes or []))
    if not clean_scopes or any(scope not in API_TOKEN_SCOPES for scope in clean_scopes):
        raise ValueError('Select at least one valid token scope')
    if isinstance(expires_days, bool) or expires_days not in {None, 30, 90, 365}:
        raise ValueError('Token expiration must be 30, 90, 365 days, or never')

    active_count = db.session.execute(
        select(ApiToken).where(
            ApiToken.user_id == user.id,
            ApiToken.revoked_at.is_(None),
        )
    ).scalars().all()
    if len(active_count) >= 20:
        raise ValueError('Revoke an existing token before creating another')

    prefix = secrets.token_urlsafe(9)[:12]
    secret = secrets.token_urlsafe(32)
    raw_token = f'gst_{prefix}.{secret}'
    now = datetime.now(timezone.utc)
    token = ApiToken(
        user_id=user.id,
        name=clean_name,
        prefix=prefix,
        token_hash=_token_digest(raw_token),
        scopes=clean_scopes,
        created_at=now,
        expires_at=now + timedelta(days=expires_days) if expires_days else None,
    )
    db.session.add(token)
    db.session.commit()
    return token, raw_token


def authenticate_api_token(raw_token, required_scope=None):
    from sharewarez import db
    from sharewarez.models import ApiToken

    if not raw_token or not raw_token.startswith('gst_') or '.' not in raw_token:
        return None, 'Invalid API token'
    prefix = raw_token[4:].split('.', 1)[0]
    token = db.session.execute(select(ApiToken).where(ApiToken.prefix == prefix)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if token is None or token.revoked_at is not None:
        return None, 'Invalid API token'
    if token.expires_at is not None and token.expires_at <= now:
        return None, 'API token expired'
    if not hmac.compare_digest(token.token_hash, _token_digest(raw_token)):
        return None, 'Invalid API token'
    if required_scope and required_scope not in (token.scopes or []):
        return None, f'Missing required scope: {required_scope}'

    token.last_used_at = now
    db.session.commit()
    return token, None


def require_api_scope(scope):
    if scope not in API_TOKEN_SCOPES:
        raise ValueError(f'Unknown API token scope: {scope}')

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            authorization = request.headers.get('Authorization', '')
            scheme, _, raw_token = authorization.partition(' ')
            if scheme.lower() != 'bearer' or not raw_token:
                return jsonify({'error': 'Bearer token required'}), 401
            token, error = authenticate_api_token(raw_token, scope)
            if token is None:
                status = 403 if error and error.startswith('Missing required scope') else 401
                return jsonify({'error': error}), status
            g.api_token = token
            g.api_user = token.user
            return view(*args, **kwargs)
        return wrapped
    return decorator
