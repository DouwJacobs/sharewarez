import json
import re

from sqlalchemy import and_, extract, func, not_, or_, select, true

from sharewarez import db
from sharewarez.models import Collection, CollectionGame, Developer, Game, GameTag, Genre, Library, Platform, Publisher, Theme


FEATURED_COLLECTION_SLUG = 'featured-games'
SMART_FIELDS = {
    'name', 'library', 'genre', 'theme', 'tag', 'platform', 'developer',
    'publisher', 'rating', 'release_year', 'size', 'downloads',
    'has_updates', 'has_extras',
}
TEXT_OPERATORS = {'equals', 'not_equals', 'contains', 'not_contains'}
NUMBER_OPERATORS = {'equals', 'not_equals', 'gte', 'lte', 'gt', 'lt'}
BOOLEAN_OPERATORS = {'equals'}
SMART_SORTS = {
    'name': Game.name,
    'rating': Game.rating,
    'release_date': Game.first_release_date,
    'date_added': Game.date_created,
    'downloads': Game.times_downloaded,
    'size': Game.size,
}


def collection_visibility_clause(user):
    """Return the SQL predicate for collections visible to a signed-in user."""
    if getattr(user, 'role', None) == 'admin':
        return true()
    return or_(Collection.visibility == 'shared', Collection.owner_id == user.id)


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


def parse_smart_rules(value):
    """Parse and strictly validate a smart-collection rules document."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Rules must be valid JSON: {exc.msg}') from exc
    if not isinstance(value, dict):
        raise ValueError('Rules must be a JSON object.')
    match = value.get('match', 'all')
    if match not in {'all', 'any'}:
        raise ValueError('Rules match must be "all" or "any".')
    conditions = value.get('conditions')
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 20:
        raise ValueError('Rules require between 1 and 20 conditions.')
    normalized = []
    for index, condition in enumerate(conditions, start=1):
        if not isinstance(condition, dict):
            raise ValueError(f'Condition {index} must be an object.')
        field = condition.get('field')
        operator = condition.get('operator', 'equals')
        raw_value = condition.get('value')
        if field not in SMART_FIELDS:
            raise ValueError(f'Condition {index} uses unsupported field {field!r}.')
        if field in {'rating', 'release_year', 'size', 'downloads'}:
            if operator not in NUMBER_OPERATORS:
                raise ValueError(f'Condition {index} has an invalid numeric operator.')
            try:
                raw_value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f'Condition {index} requires a number.') from exc
        elif field in {'has_updates', 'has_extras'}:
            if operator not in BOOLEAN_OPERATORS or not isinstance(raw_value, bool):
                raise ValueError(f'Condition {index} requires a boolean value.')
        else:
            if operator not in TEXT_OPERATORS or not isinstance(raw_value, str) or not raw_value.strip():
                raise ValueError(f'Condition {index} requires a non-empty text value.')
            raw_value = raw_value.strip()[:255]
        normalized.append({'field': field, 'operator': operator, 'value': raw_value})
    return {'match': match, 'conditions': normalized}


def _text_expression(column, operator, value):
    lowered = func.lower(column)
    target = value.lower()
    expressions = {
        'equals': lowered == target,
        'not_equals': lowered != target,
        'contains': lowered.contains(target, autoescape=True),
        'not_contains': not_(lowered.contains(target, autoescape=True)),
    }
    return expressions[operator]


def _number_expression(column, operator, value):
    return {
        'equals': column == value, 'not_equals': column != value,
        'gte': column >= value, 'lte': column <= value,
        'gt': column > value, 'lt': column < value,
    }[operator]


def _relationship_text(relationship, column, operator, value):
    if operator == 'not_equals':
        return not_(relationship.any(_text_expression(column, 'equals', value)))
    if operator == 'not_contains':
        return not_(relationship.any(_text_expression(column, 'contains', value)))
    return relationship.any(_text_expression(column, operator, value))


def _condition_expression(condition):
    field, operator, value = condition['field'], condition['operator'], condition['value']
    if field == 'name':
        return _text_expression(Game.name, operator, value)
    if field == 'library':
        return Game.library.has(_text_expression(Library.name, operator, value))
    if field == 'genre':
        return _relationship_text(Game.genres, Genre.name, operator, value)
    if field == 'theme':
        return _relationship_text(Game.themes, Theme.name, operator, value)
    if field == 'tag':
        return _relationship_text(Game.tags, GameTag.name, operator, value)
    if field == 'platform':
        return _relationship_text(Game.platforms, Platform.name, operator, value)
    if field == 'developer':
        return Game.developer.has(_text_expression(Developer.name, operator, value))
    if field == 'publisher':
        return Game.publisher.has(_text_expression(Publisher.name, operator, value))
    if field == 'release_year':
        return _number_expression(extract('year', Game.first_release_date), operator, value)
    if field == 'rating':
        return _number_expression(Game.rating, operator, value)
    if field == 'size':
        return _number_expression(Game.size, operator, value)
    if field == 'downloads':
        return _number_expression(Game.times_downloaded, operator, value)
    relation = Game.updates if field == 'has_updates' else Game.extras
    return relation.any() if value else not_(relation.any())


def smart_collection_statement(rules, sort='name', sort_order='asc', limit=24):
    rules = parse_smart_rules(rules)
    if sort not in SMART_SORTS:
        raise ValueError(f'Unsupported smart collection sort: {sort!r}.')
    if sort_order not in {'asc', 'desc'}:
        raise ValueError('Smart collection sort order must be asc or desc.')
    expressions = [_condition_expression(item) for item in rules['conditions']]
    predicate = and_(*expressions) if rules['match'] == 'all' else or_(*expressions)
    sort_column = SMART_SORTS[sort]
    ordering = sort_column.desc().nullslast() if sort_order == 'desc' else sort_column.asc().nullslast()
    return select(Game).where(predicate).order_by(ordering, Game.name.asc()).limit(max(1, min(int(limit), 200)))


def evaluate_smart_collection(collection, limit=None):
    if not collection.is_smart or not collection.smart_rules:
        return [link.game for link in collection.game_links]
    statement = smart_collection_statement(
        collection.smart_rules, collection.smart_sort, collection.smart_sort_order,
        limit if limit is not None else collection.smart_limit,
    )
    return db.session.execute(statement).scalars().unique().all()
