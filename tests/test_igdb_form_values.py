from unittest.mock import patch
from uuid import uuid4

import pytest

from sharewarez.utils.igdb_forms import igdb_form_values


@pytest.fixture
def admin_user(db_session):
    from sharewarez.models import User
    marker = uuid4().hex
    user = User(name='form_admin_' + marker, email=marker + '@forms.test', role='admin', password_hash='unused')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def provider_game():
    return {
        'id': 123456, 'name': 'Provider title', 'summary': 'Provider summary',
        'category': 14, 'status': 6, 'first_release_date': 946684800,
        'aggregated_rating': 82.5, 'videos': [{'video_id': 'abc123'}],
        'genres': [{'id': 8, 'name': 'Platform'}],
        'involved_companies': [
            {'company': {'name': 'Provider studio'}, 'developer': True},
            {'company': {'name': 'Provider publisher'}, 'publisher': True},
        ],
    }


def test_real_igdb_fields_map_to_form_contract(provider_game):
    values = igdb_form_values(provider_game)
    assert values['category'] == 'UPDATE'
    assert values['status'] == 'CANCELLED'
    assert values['first_release_date'] == '2000-01-01'
    assert values['aggregated_rating'] == 82.5
    assert values['video_urls'] == 'https://www.youtube.com/embed/abc123'
    assert values['developer'] == 'Provider studio'
    assert values['publisher'] == 'Provider publisher'
    assert values['genres'] == ['Platform']


@pytest.mark.parametrize('endpoint', ['/api/search_igdb_by_id?igdb_id=123456', '/api/search_igdb_by_name?name=Provider'])
def test_both_lookups_share_mapping_and_retain_raw_payload(endpoint, provider_game, client, admin_user):
    with client.session_transaction() as session:
        session['_user_id'] = str(admin_user.id)
        session['_fresh'] = True
    with patch('sharewarez.routes_apis.igdb.make_igdb_api_request', return_value=[provider_game]):
        response = client.get(endpoint)
    assert response.status_code == 200
    game = response.json['results'][0] if 'results' in response.json else response.json
    assert game['category'] == 14
    assert game['form_values'] == igdb_form_values(provider_game)
