from uuid import uuid4

from sqlalchemy import select

from sharewarez.models import Collection, CollectionGame, Game, Library
from sharewarez.platform import LibraryPlatform


def test_featured_collection_is_seeded_once(app, db_session):
    from sharewarez.init_manager import InitializationManager

    manager = InitializationManager()
    manager._init_featured_collection(db_session)
    db_session.commit()
    manager._init_featured_collection(db_session)
    db_session.commit()
    featured = db_session.execute(
        select(Collection).where(Collection.is_featured.is_(True))
    ).scalars().all()

    assert len(featured) == 1
    assert featured[0].slug == 'featured-games'
    assert featured[0].show_on_discover is False


def test_collection_preserves_curated_game_order(db_session):
    library = Library(
        name=f'Collection Library {uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    games = [
        Game(name=f'Collection Game {index} {uuid4().hex[:6]}', library_uuid=library.uuid)
        for index in range(3)
    ]
    collection = Collection(
        name=f'RPG Favourites {uuid4().hex[:8]}',
        slug=f'rpg-favourites-{uuid4().hex[:8]}',
        show_on_discover=True,
    )
    db_session.add_all([library, collection, *games])
    db_session.flush()
    db_session.add_all([
        CollectionGame(collection=collection, game=games[2], display_order=0),
        CollectionGame(collection=collection, game=games[0], display_order=1),
        CollectionGame(collection=collection, game=games[1], display_order=2),
    ])
    db_session.commit()
    db_session.expire_all()

    saved = db_session.get(Collection, collection.id)
    assert [game.uuid for game in saved.games] == [
        games[2].uuid,
        games[0].uuid,
        games[1].uuid,
    ]


def test_deleting_collection_does_not_delete_games(db_session):
    library = Library(
        name=f'Delete Collection Library {uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    game = Game(name=f'Persistent Game {uuid4().hex[:8]}', library_uuid=library.uuid)
    collection = Collection(
        name=f'Temporary Collection {uuid4().hex[:8]}',
        slug=f'temporary-{uuid4().hex[:8]}',
    )
    db_session.add_all([library, game, collection])
    db_session.flush()
    db_session.add(CollectionGame(collection=collection, game=game, display_order=0))
    db_session.commit()
    game_uuid = game.uuid

    db_session.delete(collection)
    db_session.commit()

    assert db_session.execute(
        select(CollectionGame).where(CollectionGame.game_uuid == game_uuid)
    ).scalar_one_or_none() is None
    assert db_session.execute(
        select(Game).where(Game.uuid == game_uuid)
    ).scalar_one_or_none() is not None
