"""Central HTTP boundary and abuse-protection policy."""

from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.http import parse_list_header


limiter = Limiter(key_func=get_remote_address)


def asgi_origin(app, scope):
    """Match the explicitly configured Flask ProxyFix host/proto trust boundary."""
    headers = dict(scope.get('headers', []))
    host = headers.get(b'host', b'').decode('latin1')
    scheme = scope.get('scheme', 'http')
    count = app.config.get('TRUST_PROXY_COUNT', 0)
    if count:
        hosts = parse_list_header(headers.get(b'x-forwarded-host', b'').decode('latin1'))
        protocols = parse_list_header(headers.get(b'x-forwarded-proto', b'').decode('latin1'))
        if len(hosts) >= count:
            host = hosts[-count]
        if len(protocols) >= count:
            scheme = protocols[-count]
    return host, scheme


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
