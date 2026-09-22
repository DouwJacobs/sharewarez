from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from sharewarez import db
from sharewarez.models import Game, GameExternalIdentity, GameGroup, GameRelationship


IGDB_RELATIONSHIP_FIELDS = {
    'parent_game': 'parent',
    'version_parent': 'edition_of',
    'dlcs': 'dlc',
    'expansions': 'expansion',
    'standalone_expansions': 'standalone_expansion',
    'remakes': 'remake',
    'remasters': 'remaster',
    'expanded_games': 'expanded_game',
    'ports': 'platform_port',
    'bundles': 'bundle',
}

RELATIONSHIP_LABELS = {
    'parent': 'Parent game',
    'edition_of': 'Edition of',
    'dlc': 'DLC',
    'expansion': 'Expansions',
    'standalone_expansion': 'Standalone expansions',
    'remake': 'Remakes',
    'remaster': 'Remasters',
    'expanded_game': 'Expanded games',
    'platform_port': 'Platform versions',
    'bundle': 'Bundles',
}

IGDB_RELATIONSHIP_QUERY_FIELDS = ', '.join(
    [f'{field}.name' for field in IGDB_RELATIONSHIP_FIELDS]
    + ['collections.name', 'franchises.name']
)


def _references(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _reference_data(reference):
    if isinstance(reference, dict):
        return reference.get('id'), (reference.get('name') or '').strip()
    try:
        return int(reference), ''
    except (TypeError, ValueError):
        return None, ''


def sync_game_relationships(game, metadata, provider='igdb'):
    """Replace provider-owned relationships and group memberships for a game."""
    if not game.uuid or not isinstance(metadata, dict):
        return

    db.session.execute(
        delete(GameRelationship).where(
            GameRelationship.game_uuid == game.uuid,
            GameRelationship.provider == provider,
        )
    )

    for field, relationship_type in IGDB_RELATIONSHIP_FIELDS.items():
        for reference in _references(metadata.get(field)):
            related_id, related_name = _reference_data(reference)
            related_external_id = str(related_id or '').strip()
            if not related_external_id:
                continue
            related_identity = db.session.execute(
                select(GameExternalIdentity).where(
                    GameExternalIdentity.provider == provider,
                    GameExternalIdentity.external_id == related_external_id,
                )
            ).scalar_one_or_none()
            related_game = related_identity.game if related_identity else None
            legacy_igdb_id = int(related_external_id) if provider == 'igdb' and related_external_id.isdigit() else None
            if related_game is None and legacy_igdb_id is not None:
                related_game = db.session.execute(
                    select(Game).where(Game.igdb_id == legacy_igdb_id)
                ).scalar_one_or_none()
            if related_game is game:
                continue
            if not related_name and related_game:
                related_name = related_game.name
            if not related_name:
                related_name = f'{provider.upper()} game {related_external_id}'
            db.session.add(GameRelationship(
                game_uuid=game.uuid,
                related_game_uuid=related_game.uuid if related_game else None,
                related_igdb_id=legacy_igdb_id,
                related_external_id=related_external_id,
                related_name=related_name,
                relationship_type=relationship_type,
                provider=provider,
            ))

    game.groups = [group for group in game.groups if group.provider != provider]
    for field, group_type in (('collections', 'series'), ('franchises', 'franchise')):
        for reference in _references(metadata.get(field)):
            provider_id, name = _reference_data(reference)
            provider_id = str(provider_id or '').strip()
            if not provider_id or not name:
                continue
            group = db.session.execute(
                select(GameGroup).where(
                    GameGroup.provider == provider,
                    GameGroup.provider_id == provider_id,
                    GameGroup.group_type == group_type,
                )
            ).scalar_one_or_none()
            if group is None:
                group = GameGroup(
                    provider=provider,
                    provider_id=provider_id,
                    name=name,
                    group_type=group_type,
                )
                db.session.add(group)
            else:
                group.name = name
            if group not in game.groups:
                game.groups.append(group)

    canonical_identity = next(
        (identity for identity in game.external_identities if identity.canonical),
        None,
    )
    if canonical_identity:
        db.session.execute(
            update(GameRelationship)
            .where(
                GameRelationship.provider == canonical_identity.provider,
                GameRelationship.related_external_id == canonical_identity.external_id,
                GameRelationship.related_game_uuid.is_(None),
            )
            .values(related_game_uuid=game.uuid, related_name=game.name, updated_at=datetime.now(timezone.utc))
        )


def serialize_game_relationships(game, excluded_types=None):
    excluded_types = set(excluded_types or ())
    grouped = {}
    for relationship in sorted(game.relationships, key=lambda item: (item.relationship_type, item.related_name.casefold())):
        if relationship.relationship_type in excluded_types:
            continue
        grouped.setdefault(relationship.relationship_type, []).append({
            'name': relationship.related_name,
            'igdb_id': relationship.related_igdb_id,
            'provider': getattr(relationship, 'provider', 'igdb'),
            'provider_game_id': str(
                getattr(relationship, 'related_external_id', None)
                or relationship.related_igdb_id
            ),
            'game_uuid': relationship.related_game_uuid,
        })
    return [
        {'type': relationship_type, 'label': RELATIONSHIP_LABELS.get(relationship_type, relationship_type.replace('_', ' ').title()), 'games': games}
        for relationship_type, games in grouped.items()
    ]


def serialize_game_families(game):
    names = {}
    for group in game.groups:
        names.setdefault(group.name.casefold(), group.name)
    return sorted(names.values())
