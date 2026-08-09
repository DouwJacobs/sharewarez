from uuid import uuid4

import pytest

from sharewarez.models import Collection, Game, Genre, Library, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.collections import evaluate_smart_collection, parse_smart_rules


def make_library(db_session):
    library = Library(name=f'Smart Library {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    return library


def test_smart_collection_matches_all_conditions(db_session):
    library = make_library(db_session)
    genre_name = f'RPG-{uuid4().hex[:8]}'
    rpg = Genre(name=genre_name)
    matching = Game(name='Alpha Quest', library_uuid=library.uuid, rating=91, genres=[rpg])
    low_rating = Game(name='Beta Quest', library_uuid=library.uuid, rating=60, genres=[rpg])
    other = Game(name='Gamma Racer', library_uuid=library.uuid, rating=95)
    collection = Collection(
        name=f'Smart RPGs {uuid4().hex[:8]}', slug=f'smart-rpg-{uuid4().hex[:8]}',
        is_smart=True, smart_rules={'match': 'all', 'conditions': [
            {'field': 'genre', 'operator': 'equals', 'value': genre_name},
            {'field': 'rating', 'operator': 'gte', 'value': 80},
        ]}, smart_sort='rating', smart_sort_order='desc', smart_limit=10,
    )
    db_session.add_all([matching, low_rating, other, collection])
    db_session.commit()

    assert [game.uuid for game in evaluate_smart_collection(collection)] == [matching.uuid]
    assert collection.games[0].uuid == matching.uuid


def test_smart_collection_supports_any_sort_and_limit(db_session):
    library = make_library(db_session)
    suffix = uuid4().hex[:8]
    games = [
        Game(name=f'Zulu-{suffix}', library_uuid=library.uuid, times_downloaded=2),
        Game(name=f'Alpha-{suffix}', library_uuid=library.uuid, times_downloaded=10),
        Game(name=f'Bravo-{suffix}', library_uuid=library.uuid, times_downloaded=5),
    ]
    collection = Collection(
        name=f'Popular {uuid4().hex[:8]}', slug=f'popular-{uuid4().hex[:8]}',
        is_smart=True, smart_rules={'match': 'any', 'conditions': [
            {'field': 'name', 'operator': 'equals', 'value': games[0].name},
            {'field': 'name', 'operator': 'equals', 'value': games[1].name},
        ]}, smart_sort='downloads', smart_sort_order='desc', smart_limit=2,
    )
    db_session.add_all([*games, collection])
    db_session.commit()

    assert [game.name for game in evaluate_smart_collection(collection)] == [games[1].name, games[0].name]


@pytest.mark.parametrize('rules', [
    {},
    {'match': 'invalid', 'conditions': [{'field': 'name', 'value': 'x'}]},
    {'match': 'all', 'conditions': []},
    {'match': 'all', 'conditions': [{'field': 'password', 'operator': 'equals', 'value': 'x'}]},
    {'match': 'all', 'conditions': [{'field': 'rating', 'operator': 'contains', 'value': 5}]},
])
def test_invalid_smart_rules_are_rejected(rules):
    with pytest.raises(ValueError):
        parse_smart_rules(rules)


def test_admin_can_preview_smart_collection(client, db_session):
    library = make_library(db_session)
    game = Game(name=f'Preview Target {uuid4().hex[:8]}', library_uuid=library.uuid, rating=88)
    suffix = uuid4().hex[:8]
    admin = User(
        user_id=str(uuid4()), name=f'smart-admin-{suffix}',
        email=f'smart-admin-{suffix}@example.test', role='admin', is_email_verified=True,
    )
    admin.set_password('test-password')
    db_session.add_all([game, admin])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True

    response = client.post('/admin/api/collections/smart-preview', json={
        'rules': {'match': 'all', 'conditions': [
            {'field': 'name', 'operator': 'equals', 'value': game.name},
        ]},
        'sort': 'name', 'limit': 10,
    })
    assert response.status_code == 200
    assert response.get_json()['games'][0]['uuid'] == game.uuid


def test_admin_can_create_smart_collection(client, db_session):
    suffix = uuid4().hex[:8]
    admin = User(
        user_id=str(uuid4()), name=f'smart-create-admin-{suffix}',
        email=f'smart-create-admin-{suffix}@example.test', role='admin', is_email_verified=True,
    )
    admin.set_password('test-password')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True

    name = f'Highly Rated {suffix}'
    response = client.post('/admin/collections/new', data={
        'name': name, 'description': 'Generated automatically',
        'show_on_discover': 'y', 'display_order': '5', 'is_smart': 'y',
        'smart_rules': '{"match":"all","conditions":[{"field":"rating","operator":"gte","value":85}]}',
        'smart_sort': 'rating', 'smart_sort_order': 'desc', 'smart_limit': '12',
        'game_order': '', 'submit': 'Save collection',
    })
    assert response.status_code == 302
    collection = db_session.query(Collection).filter_by(name=name).one()
    assert collection.is_smart is True
    assert collection.smart_rules['conditions'][0]['value'] == 85.0
    assert collection.smart_sort == 'rating'
    assert collection.smart_limit == 12
    assert collection.game_links == []


def test_collection_editor_explains_smart_rules_json(client, db_session):
    suffix = uuid4().hex[:8]
    admin = User(
        user_id=str(uuid4()), name=f'smart-help-admin-{suffix}',
        email=f'smart-help-admin-{suffix}@example.test', role='admin',
        is_email_verified=True,
    )
    admin.set_password('test-password')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True

    response = client.get('/admin/collections/new')

    assert response.status_code == 200
    assert b'How to write smart rules JSON' in response.data
    assert b'between 1 and 20 conditions' in response.data
    assert b'not_contains' in response.data
    assert b'Size uses the stored byte count' in response.data
