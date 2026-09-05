"""Production request diagnostics with stable, machine-readable fields."""

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

from flask import g, request


_REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,64}$')


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname.lower(),
            'logger': record.name,
            'message': record.getMessage(),
        }
        for key in ('request_id', 'method', 'path', 'status', 'duration_ms', 'remote_addr'):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def normalize_request_id(supplied):
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid4().hex


def _request_id():
    return normalize_request_id(request.headers.get('X-Request-ID', ''))


def init_observability(app):
    """Install request correlation, timing, and structured access logging."""
    request_logger = logging.getLogger('gamelibrary.request')
    request_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if app.config.get('LOG_FORMAT', 'json') == 'json':
        handler.setFormatter(JsonFormatter())
    request_logger.addHandler(handler)
    request_logger.setLevel(app.config.get('LOG_LEVEL', 'INFO'))
    request_logger.propagate = False

    @app.before_request
    def begin_request_diagnostics():
        g.request_id = _request_id()
        g.request_started_at = time.perf_counter()

    @app.after_request
    def finish_request_diagnostics(response):
        started_at = getattr(g, 'request_started_at', None)
        req_id = getattr(g, 'request_id', None) or _request_id()
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at else 0.0
        response.headers['X-Request-ID'] = req_id
        response.headers['Server-Timing'] = f'app;dur={duration_ms}'
        if request.endpoint not in {'health.live'}:
            request_logger.info(
                'request completed',
                extra={
                    'request_id': req_id,
                    'method': request.method,
                    'path': request.url_rule.rule if request.url_rule is not None else '<unmatched>',
                    'status': response.status_code,
                    'duration_ms': duration_ms,
                    'remote_addr': request.remote_addr,
                },
            )
        return response
