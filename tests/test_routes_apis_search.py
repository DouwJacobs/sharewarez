from uuid import uuid4

import pytest

from sharewarez import db
from sharewarez.models import Game, GameRequest, Library, User
from sharewarez.platform import LibraryPlatform


@pytest.fixture
def search_records(db_session):
    suffix = str(uuid4())[:8]
    library = Library(name=f'Arcade {suffix}', platform=LibraryPlatform.OTHER)
    user = User(name=f'player_{suffix}', email=f'player_{suffix}@example.com', role='admin', user_id=str(uuid4()))
    user.set_password('test-password')
    db_session.add_all([library, user])
    db_session.flush()
    game = Game(name=f'Commander Keen {suffix}', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()
    return user, library, game


def login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_search_requires_login(client):
    assert client.get('/api/global-search?q=keen').status_code == 302


def test_search_requires_two_characters(client, search_records):
    user, _, _ = search_records
    login(client, user)
    response = client.get('/api/global-search?q=k')
    assert response.status_code == 200
    assert response.get_json()['results'] == []


def test_search_returns_game_and_library_results(client, search_records):
    user, library, game = search_records
    login(client, user)
    game_results = client.get('/api/global-search?q=Commander').get_json()['results']
    library_results = client.get('/api/global-search?q=Arcade').get_json()['results']
    assert any(result['title'] == game.name and result['type'] == 'Game' for result in game_results)
    assert any(result['title'] == library.name and result['type'] == 'Library' for result in library_results)


def test_search_tolerates_typographical_errors(client, search_records):
    user, _, game = search_records
    login(client, user)
    results = client.get('/api/global-search?q=Comander%20Ken').get_json()['results']
    assert any(result['title'] == game.name and result['type'] == 'Game' for result in results)


def test_admin_search_returns_request_results(client, search_records, db_session):
    user, _, _ = search_records
    login(client, user)
    suffix = str(uuid4())[:8]
    game_request = GameRequest(
        igdb_id=1_700_000_000 + (uuid4().int % 300_000_000),
        parent_igdb_id=1_400_000_000 + (uuid4().int % 300_000_000),
        parent_game_name=f'Requested Adventure {suffix}',
        game_name=f'Requested Adventure Gold {suffix}',
        edition_name='Gold Edition',
    )
    db_session.add(game_request)
    db_session.commit()

    results = client.get('/api/global-search?q=Requested Adventure').get_json()['results']
    assert any(
        result['type'] == 'Request' and result['title'] == game_request.game_name
        and result['url'] == f'/admin/game-requests/{game_request.id}'
        for result in results
    )
