from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from sharewarez.models import Game, GameExternalIdentity, GameRequest, Library
from sharewarez.platform import LibraryPlatform


def _library(db_session):
    library = Library(
        name=f'Provider identities {uuid4().hex}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.flush()
    return library


def _game(db_session, library, name):
    game = Game(name=name, library_uuid=library.uuid, size=0)
    db_session.add(game)
    db_session.flush()
    return game


def test_game_can_store_multiple_provider_identities(db_session):
    library = _library(db_session)
    game = _game(db_session, library, 'Multiple identities')
    game.external_identities.extend([
        GameExternalIdentity(
            provider='igdb',
            external_id='1001',
            canonical=True,
            provider_url='https://www.igdb.com/games/example',
        ),
        GameExternalIdentity(
            provider='rawg',
            external_id='example-slug',
            provider_url='https://rawg.io/games/example-slug',
        ),
    ])
    db_session.commit()

    identities = {
        item.provider: (item.external_id, item.canonical)
        for item in game.external_identities
    }
    assert identities == {
        'igdb': ('1001', True),
        'rawg': ('example-slug', False),
    }


def test_provider_identity_is_globally_unique(db_session):
    library = _library(db_session)
    first = _game(db_session, library, 'First identity owner')
    second = _game(db_session, library, 'Second identity owner')
    db_session.add_all([
        GameExternalIdentity(game=first, provider='rawg', external_id='shared'),
        GameExternalIdentity(game=second, provider='rawg', external_id='shared'),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_game_has_only_one_canonical_identity(db_session):
    library = _library(db_session)
    game = _game(db_session, library, 'Canonical identity')
    db_session.add_all([
        GameExternalIdentity(
            game=game,
            provider='igdb',
            external_id='2001',
            canonical=True,
        ),
        GameExternalIdentity(
            game=game,
            provider='rawg',
            external_id='canonical-two',
            canonical=True,
        ),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_provider_identity_cascades_with_game_deletion(db_session):
    library = _library(db_session)
    game = _game(db_session, library, 'Cascade identity')
    identity = GameExternalIdentity(
        game=game,
        provider='igdb',
        external_id='3001',
        canonical=True,
    )
    db_session.add(identity)
    db_session.commit()
    identity_id = identity.id

    db_session.delete(game)
    db_session.commit()

    assert db_session.get(GameExternalIdentity, identity_id) is None


def test_new_game_requests_are_unique_per_provider_identity(db_session):
    first = GameRequest(
        request_type='new_game',
        metadata_provider='rawg',
        provider_game_id='request-identity',
        game_name='First request',
    )
    duplicate = GameRequest(
        request_type='new_game',
        metadata_provider='rawg',
        provider_game_id='request-identity',
        game_name='Duplicate request',
    )
    db_session.add_all([first, duplicate])

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
