from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from sharewarez.models import Game, GameRequest, GameRequestUser, GlobalSettings, Library, User
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.game_requests import (
    create_or_join_request,
    normalize_igdb_game,
    search_igdb_games,
    update_request_status,
    update_request_preferences,
    withdraw_request,
)
from sharewarez.utils.request_notifications import notify_request_updated


def make_user(db_session, role='user'):
    token = uuid4().hex[:10]
    user = User(
        user_id=str(uuid4()), name=f'Requester_{token}', email=f'{token}@test.invalid',
        role=role, state=True, is_email_verified=True,
    )
    user.set_password('test-password')
    db_session.add(user)
    db_session.commit()
    return user


def ensure_settings(db_session, **overrides):
    settings = db_session.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings(settings={})
        db_session.add(settings)
    values = dict(settings.settings or {})
    values.update({'enableGameRequests': True, 'maxActiveRequestsPerUser': 20})
    values.update(overrides)
    settings.settings = values
    db_session.commit()


def snapshot(igdb_id=100, parent_id=100, edition=None):
    return {
        'igdb_id': igdb_id, 'parent_igdb_id': parent_id,
        'parent_game_name': 'Example Game',
        'game_name': 'Example Game' if not edition else f'Example Game: {edition}',
        'edition_name': edition, 'cover_url': None, 'summary': 'Summary',
        'platforms': ['PC'], 'first_release_date': datetime.now(timezone.utc),
    }


def unique_igdb_id():
    return 1_500_000_000 + (uuid4().int % 400_000_000)


def test_normalize_igdb_edition_uses_parent_group():
    result = normalize_igdb_game({
        'id': 102, 'name': 'Example Gold', 'version_parent': {'id': 100, 'name': 'Example Game'},
        'version_title': 'Gold Edition', 'platforms': [{'name': 'PC'}],
        'cover': {'image_id': 'cover123'},
    })
    assert result['igdb_id'] == 102
    assert result['parent_igdb_id'] == 100
    assert result['parent_game_name'] == 'Example Game'
    assert result['edition_name'] == 'Gold Edition'
    assert result['cover_url'].endswith('/cover123.jpg')


@patch('sharewarez.utils.game_requests.make_igdb_api_request')
def test_request_search_uses_bounded_ttl_cache(mock_api):
    term = f'Cache Test {uuid4().hex}'
    mock_api.return_value = [{'id': unique_igdb_id(), 'name': 'Cached Game'}]

    first, first_error = search_igdb_games(term)
    first[0]['game_name'] = 'Mutated locally'
    second, second_error = search_igdb_games(term)

    assert first_error is None and second_error is None
    assert second[0]['game_name'] == 'Cached Game'
    mock_api.assert_called_once()


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_users_join_same_exact_edition_without_duplicate_request(mock_fetch, db_session):
    ensure_settings(db_session)
    first_user = make_user(db_session)
    second_user = make_user(db_session)
    edition_id = unique_igdb_id()
    mock_fetch.return_value = snapshot(edition_id, edition_id - 1, 'Gold Edition')

    first_request, _ = create_or_join_request(first_user, edition_id, 'Gold please', False)
    second_request, _ = create_or_join_request(second_user, edition_id, None, True)

    assert first_request.id == second_request.id
    assert db_session.query(GameRequest).filter_by(igdb_id=edition_id).count() == 1
    assert db_session.query(GameRequestUser).filter_by(request_id=first_request.id).count() == 2
    assert len(first_request.active_requesters) == 2


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_user_cannot_request_same_edition_twice(mock_fetch, db_session):
    ensure_settings(db_session)
    user = make_user(db_session)
    edition_id = unique_igdb_id()
    mock_fetch.return_value = snapshot(edition_id, edition_id)
    create_or_join_request(user, edition_id)
    with pytest.raises(ValueError, match='already requested'):
        create_or_join_request(user, edition_id)


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_user_can_edit_active_request_preferences(mock_fetch, db_session):
    ensure_settings(db_session)
    user = make_user(db_session)
    edition_id = unique_igdb_id()
    mock_fetch.return_value = snapshot(edition_id, edition_id)
    game_request, link = create_or_join_request(user, edition_id)

    updated = update_request_preferences(user, game_request.id, 'Updated details', True)

    assert updated.id == link.id
    assert updated.requester_note == 'Updated details'
    assert updated.accept_any_edition is True


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_last_withdrawal_cancels_request(mock_fetch, db_session):
    ensure_settings(db_session)
    user = make_user(db_session)
    edition_id = unique_igdb_id()
    mock_fetch.return_value = snapshot(edition_id, edition_id)
    game_request, _ = create_or_join_request(user, edition_id)
    withdraw_request(user, game_request.id)
    assert game_request.status == 'cancelled'
    assert game_request.resolved_at is not None


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_fulfilled_status_requires_library_game(mock_fetch, db_session):
    ensure_settings(db_session)
    user = make_user(db_session)
    admin = make_user(db_session, role='admin')
    edition_id = unique_igdb_id()
    mock_fetch.return_value = snapshot(edition_id, edition_id)
    game_request, _ = create_or_join_request(user, edition_id)
    with pytest.raises(ValueError, match='library game'):
        update_request_status(game_request, admin, 'fulfilled')


def test_game_already_in_library_cannot_be_requested(db_session):
    ensure_settings(db_session)
    user = make_user(db_session)
    igdb_id = unique_igdb_id()
    library = Library(uuid=str(uuid4()), name='Available games', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    db_session.add(Game(
        uuid=str(uuid4()), igdb_id=igdb_id, name='Already Available',
        library_uuid=library.uuid, size=1,
    ))
    db_session.commit()

    with pytest.raises(ValueError, match='already available'):
        create_or_join_request(user, igdb_id)


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_fulfilling_related_edition_satisfies_flexible_requesters_only(mock_fetch, db_session):
    ensure_settings(db_session)
    exact_user = make_user(db_session)
    flexible_user = make_user(db_session)
    gold_user = make_user(db_session)
    admin = make_user(db_session, role='admin')
    parent_id = unique_igdb_id()
    standard_id, gold_id = parent_id + 1, parent_id + 2
    mock_fetch.side_effect = [snapshot(standard_id, parent_id, 'Standard'), snapshot(gold_id, parent_id, 'Gold')]
    standard, _ = create_or_join_request(exact_user, standard_id)
    create_or_join_request(flexible_user, standard_id, accept_any_edition=True)
    gold, _ = create_or_join_request(gold_user, gold_id)

    library = Library(uuid=str(uuid4()), name='PC', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    available_game = Game(
        uuid=str(uuid4()), igdb_id=gold_id, name='Example Gold',
        library_uuid=library.uuid, size=1,
    )
    db_session.add(available_game)
    db_session.commit()

    _, satisfied = update_request_status(gold, admin, 'fulfilled', game_uuid=available_game.uuid)

    assert {link.user_id for link in satisfied} == {gold_user.id, flexible_user.id}
    assert [link.user_id for link in standard.active_requesters] == [exact_user.id]

    _, reopened = update_request_status(gold, admin, 'reviewing')

    assert {link.user_id for link in reopened} == {gold_user.id, flexible_user.id}
    assert all(link.satisfied_at is None for link in reopened)
    assert all(link.satisfied_by_game_uuid is None for link in reopened)
    assert {link.user_id for link in standard.active_requesters} == {exact_user.id, flexible_user.id}
    assert {link.user_id for link in gold.active_requesters} == {gold_user.id}


@patch('sharewarez.utils.game_requests.fetch_igdb_game')
def test_changing_fulfilled_game_updates_existing_satisfaction(mock_fetch, db_session):
    ensure_settings(db_session)
    user = make_user(db_session)
    admin = make_user(db_session, role='admin')
    edition_id = unique_igdb_id()
    mock_fetch.return_value = snapshot(edition_id, edition_id)
    game_request, link = create_or_join_request(user, edition_id)

    library = Library(uuid=str(uuid4()), name='PC', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    first_game = Game(uuid=str(uuid4()), igdb_id=edition_id, name='First release', library_uuid=library.uuid, size=1)
    replacement_game = Game(uuid=str(uuid4()), igdb_id=edition_id + 1, name='Replacement release', library_uuid=library.uuid, size=1)
    db_session.add_all([first_game, replacement_game])
    db_session.commit()

    update_request_status(game_request, admin, 'fulfilled', game_uuid=first_game.uuid)
    _, affected = update_request_status(game_request, admin, 'fulfilled', game_uuid=replacement_game.uuid)

    assert affected == [link]
    assert link.satisfied_by_game_uuid == replacement_game.uuid
    assert game_request.fulfilled_game_uuid == replacement_game.uuid


def test_requests_page_requires_authentication(client):
    response = client.get('/requests')
    assert response.status_code == 302


@patch('sharewarez.utils.request_notifications.get_request_settings')
@patch('sharewarez.utils.request_notifications.send_email')
def test_request_update_email_deduplicates_users(mock_send, mock_settings, app, db_session):
    mock_settings.return_value = {
        'notifyDiscordRequestUpdates': False,
        'notifyRequesterRequestEmail': True,
    }
    user = make_user(db_session)
    record = SimpleNamespace(
        status='fulfilled', game_name='Example', public_response=None,
        fulfilled_game_uuid=None, active_requesters=[],
    )
    first = SimpleNamespace(user_id=user.id, user=user, withdrawn_at=None, last_notified_status=None)
    second = SimpleNamespace(user_id=user.id, user=user, withdrawn_at=None, last_notified_status=None)

    with app.app_context():
        notify_request_updated(record, [first, second])

    mock_send.assert_called_once()
