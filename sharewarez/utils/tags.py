"""Helpers for validating and assigning admin-managed game tags."""

from sqlalchemy import func, select

from sharewarez import db
from sharewarez.models import GameTag


MAX_TAGS_PER_GAME = 20
MAX_TAG_LENGTH = 50


def assign_game_tags(game, raw_tags):
    """Replace a game's tags from a comma-separated admin form value."""
    names = []
    seen_names = set()
    for value in (raw_tags or '').split(','):
        name = value.strip()
        normalized_name = name.casefold()
        if not name or normalized_name in seen_names:
            continue
        if len(name) > MAX_TAG_LENGTH:
            raise ValueError(f'Tag "{name[:20]}..." exceeds {MAX_TAG_LENGTH} characters.')
        seen_names.add(normalized_name)
        names.append(name)

    if len(names) > MAX_TAGS_PER_GAME:
        raise ValueError(f'A game can have at most {MAX_TAGS_PER_GAME} tags.')

    tags = []
    for name in names:
        tag = db.session.execute(
            select(GameTag).where(func.lower(GameTag.name) == name.casefold())
        ).scalar_one_or_none()
        if not tag:
            tag = GameTag(name=name)
            db.session.add(tag)
        tags.append(tag)

    game.tags = tags
