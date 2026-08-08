import re

from sqlalchemy import select

from sharewarez import db
from sharewarez.models import Collection, CollectionGame, Game


FEATURED_COLLECTION_SLUG = 'featured-games'


def slugify_collection_name(value):
    slug = re.sub(r'[^a-z0-9]+', '-', (value or '').strip().lower()).strip('-')
    return slug or 'collection'


def unique_collection_slug(name, collection_id=None):
    base = slugify_collection_name(name)
    candidate = base
    suffix = 2
    while db.session.execute(
        select(Collection.id).where(
            Collection.slug == candidate,
            Collection.id != collection_id if collection_id is not None else Collection.id.is_not(None),
        )
    ).scalar_one_or_none() is not None:
        candidate = f'{base}-{suffix}'
        suffix += 1
    return candidate


def replace_collection_games(collection, game_uuids):
    """Replace membership and normalize ordering from a trusted UUID sequence."""
    unique_uuids = list(dict.fromkeys(uuid for uuid in game_uuids if uuid))
    valid_uuids = set(db.session.execute(
        select(Game.uuid).where(Game.uuid.in_(unique_uuids))
    ).scalars().all()) if unique_uuids else set()

    collection.game_links.clear()
    collection.game_links.extend(
        CollectionGame(game_uuid=game_uuid, display_order=index)
        for index, game_uuid in enumerate(unique_uuids)
        if game_uuid in valid_uuids
    )


def get_featured_collection():
    return db.session.execute(
        select(Collection).where(Collection.is_featured.is_(True))
    ).scalars().first()
