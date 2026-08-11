from uuid import uuid4

from sqlalchemy import select

from sharewarez.models import Game, GameGroup, GameRelationship, Library
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.game_relationships import (
    IGDB_RELATIONSHIP_QUERY_FIELDS,
    RELATIONSHIP_LABELS,
    serialize_game_relationships,
    sync_game_relationships,
)


def test_igdb_relationship_query_uses_supported_fields():
    assert 'parent_game.name' in IGDB_RELATIONSHIP_QUERY_FIELDS
    assert 'version_parent.name' in IGDB_RELATIONSHIP_QUERY_FIELDS
    assert 'ports.name' in IGDB_RELATIONSHIP_QUERY_FIELDS
    assert 'collections.name' in IGDB_RELATIONSHIP_QUERY_FIELDS
    assert 'packs.name' not in IGDB_RELATIONSHIP_QUERY_FIELDS
    assert RELATIONSHIP_LABELS['platform_port'] == 'Platform versions'


def _library(db_session):
    library = Library(name=f'Relationships {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    return library


def test_sync_stores_relationships_and_series_memberships(db_session):
    library = _library(db_session)
    game = Game(name='Current Game', igdb_id=900001, library_uuid=library.uuid)
    db_session.add(game)
    db_session.flush()

    sync_game_relationships(game, {
        'parent_game': {'id': 900002, 'name': 'Parent Game'},
        'remakes': [{'id': 900003, 'name': 'Modern Remake'}],
        'collections': [{'id': 501, 'name': 'Example Series'}],
        'franchises': [{'id': 601, 'name': 'Example Franchise'}],
    })
    db_session.commit()

    relationships = db_session.execute(
        select(GameRelationship).where(GameRelationship.game_uuid == game.uuid)
    ).scalars().all()
    assert {(item.relationship_type, item.related_name) for item in relationships} == {
        ('parent', 'Parent Game'),
        ('remake', 'Modern Remake'),
    }
    assert {(group.group_type, group.name) for group in game.groups} == {
        ('series', 'Example Series'),
        ('franchise', 'Example Franchise'),
    }


def test_new_library_game_resolves_previously_external_relationship(db_session):
    library = _library(db_session)
    source = Game(name='Expansion', igdb_id=910001, library_uuid=library.uuid)
    db_session.add(source)
    db_session.flush()
    sync_game_relationships(source, {'parent_game': {'id': 910002, 'name': 'Base Game'}})
    db_session.commit()

    target = Game(name='Base Game', igdb_id=910002, library_uuid=library.uuid)
    db_session.add(target)
    db_session.flush()
    sync_game_relationships(target, {})
    db_session.commit()

    relationship = db_session.execute(
        select(GameRelationship).where(GameRelationship.game_uuid == source.uuid)
    ).scalar_one()
    assert relationship.related_game_uuid == target.uuid
    serialized = serialize_game_relationships(source)
    assert serialized[0]['games'][0]['game_uuid'] == target.uuid


def test_provider_refresh_replaces_old_relationships(db_session):
    library = _library(db_session)
    game = Game(name='Refresh Game', igdb_id=920001, library_uuid=library.uuid)
    db_session.add(game)
    db_session.flush()
    sync_game_relationships(game, {'dlcs': [{'id': 920002, 'name': 'Old DLC'}]})
    db_session.commit()

    sync_game_relationships(game, {'expansions': [{'id': 920003, 'name': 'New Expansion'}]})
    db_session.commit()

    saved = db_session.execute(
        select(GameRelationship).where(GameRelationship.game_uuid == game.uuid)
    ).scalars().all()
    assert [(item.relationship_type, item.related_name) for item in saved] == [
        ('expansion', 'New Expansion')
    ]
    assert db_session.execute(select(GameGroup).where(GameGroup.games.any(Game.uuid == game.uuid))).scalars().all() == []
