"""Central HTTP boundary and abuse-protection policy."""

from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix


limiter = Limiter(key_func=get_remote_address)


def security_headers(app, *, secure=False):
    """One response-header policy for Flask and direct ASGI responses."""
    headers = {
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'SAMEORIGIN',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Content-Security-Policy': app.config.get('SECURITY_CSP', "default-src 'self'"),
    }
    if secure and app.config.get('SECURITY_HSTS_ENABLED', True):
        headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return headers


def init_http_security(app):
    """Install proxy handling, request limits, and response security headers."""
    proxy_count = app.config.get('TRUST_PROXY_COUNT', 0)
    if proxy_count:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_count,
            x_proto=proxy_count,
            x_host=proxy_count,
            x_port=proxy_count,
        )

    limiter.init_app(app)

    @app.after_request
    def add_security_headers(response):
        for name, value in security_headers(app, secure=request.is_secure).items():
            response.headers.setdefault(name, value)
        return response
