from types import SimpleNamespace

import pytest
from flask import Flask

from sharewarez.routes_apis import apis_bp
from sharewarez.routes_apis.public import _game_payload, _page_payload, _pagination_args


def test_public_api_routes_require_bearer_tokens():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-key'
    app.register_blueprint(apis_bp)

    response = app.test_client().get('/api/v1/profile')

    assert response.status_code == 401
    assert response.get_json() == {'error': 'Bearer token required'}


@pytest.mark.parametrize('query', ['?page=0', '?per_page=0', '?per_page=101', '?page=nope'])
def test_pagination_rejects_invalid_values(query):
    app = Flask(__name__)
    with app.test_request_context(f'/api/v1/games{query}'):
        with pytest.raises(ValueError):
            _pagination_args()


def test_page_payload_has_stable_envelope():
    assert _page_payload([{'uuid': 'one'}], 2, 10, 21) == {
        'data': [{'uuid': 'one'}],
        'pagination': {'page': 2, 'per_page': 10, 'total': 21, 'pages': 3},
    }


def test_game_payload_does_not_expose_filesystem_paths():
    game = SimpleNamespace(
        uuid='game-uuid', name='Example', slug='example', library_uuid='library-uuid',
        cover='cover.jpg', first_release_date=None, category=None, status=None,
        rating=90.0, size=1024, version='1.0', last_updated=None,
        full_disk_path='/private/games/example', nfo_content='private',
    )

    payload = _game_payload(game)

    assert payload['uuid'] == 'game-uuid'
    assert 'full_disk_path' not in payload
    assert 'nfo_content' not in payload
