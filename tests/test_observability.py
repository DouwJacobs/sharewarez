import json

from sharewarez.observability import JsonFormatter
from sharewarez.utils.instance_health import get_instance_diagnostics


def test_health_endpoints(client):
    live = client.get('/health/live')
    ready = client.get('/health/ready')

    assert live.status_code == 200
    assert live.get_json()['status'] == 'ok'
    assert ready.status_code == 200
    assert ready.get_json()['status'] == 'ready'


def test_request_diagnostics_headers(client):
    response = client.get('/health/live', headers={'X-Request-ID': 'test-request-123'})

    assert response.headers['X-Request-ID'] == 'test-request-123'
    assert response.headers['Server-Timing'].startswith('app;dur=')


def test_invalid_request_id_is_replaced(client):
    response = client.get('/health/live', headers={'X-Request-ID': 'bad value!'})

    assert response.headers['X-Request-ID'] != 'bad value!'
    assert len(response.headers['X-Request-ID']) == 32


def test_json_formatter_exposes_only_structured_fields():
    import logging

    record = logging.LogRecord('test', logging.INFO, '', 0, 'complete', (), None)
    record.request_id = 'request-123'
    record.path = '/login'
    payload = json.loads(JsonFormatter().format(record))

    assert payload['request_id'] == 'request-123'
    assert payload['path'] == '/login'
    assert 'query' not in payload


def test_instance_diagnostics_are_safe_and_aggregated(app):
    with app.app_context():
        diagnostics = get_instance_diagnostics()

    assert diagnostics['database']['status'] == 'healthy'
    assert diagnostics['jobs']['status'] in {'healthy', 'warning'}
    assert [item['name'] for item in diagnostics['integrations']] == [
        'SMTP', 'Discord', 'IGDB',
    ]
    assert all('secret' not in item and 'password' not in item for item in diagnostics['integrations'])
