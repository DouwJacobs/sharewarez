import pytest
from flask import Flask, jsonify

from sharewarez.utils.api_tokens import (
    _token_digest,
    create_api_token,
    require_api_scope,
)


def test_token_digest_is_keyed_and_deterministic():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'first-key'
    with app.app_context():
        first = _token_digest('gst_prefix.secret')
        assert first == _token_digest('gst_prefix.secret')

    app.config['SECRET_KEY'] = 'second-key'
    with app.app_context():
        assert _token_digest('gst_prefix.secret') != first


def test_token_request_validation_runs_before_persistence():
    with pytest.raises(ValueError, match='Token name'):
        create_api_token(object(), '', ['profile:read'], 90)
    with pytest.raises(ValueError, match='valid token scope'):
        create_api_token(object(), 'automation', ['admin:write'], 90)
    with pytest.raises(ValueError, match='expiration'):
        create_api_token(object(), 'automation', ['profile:read'], 7)


def test_scoped_endpoint_requires_bearer_header():
    app = Flask(__name__)

    @app.get('/protected')
    @require_api_scope('profile:read')
    def protected():
        return jsonify({'ok': True})

    response = app.test_client().get('/protected')
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Bearer token required'}


def test_unknown_scope_cannot_be_registered():
    with pytest.raises(ValueError, match='Unknown API token scope'):
        require_api_scope('admin:write')
