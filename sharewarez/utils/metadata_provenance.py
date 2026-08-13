"""Field-level provenance and conflict handling for provider metadata."""

from datetime import datetime, timezone

from sharewarez.models import Category, Status


PROVIDER_FIELDS = (
    'name', 'summary', 'storyline', 'url', 'video_urls', 'first_release_date',
    'aggregated_rating', 'aggregated_rating_count', 'rating', 'rating_count',
    'total_rating', 'total_rating_count', 'category', 'status',
)
EDITABLE_PROVIDER_FIELDS = (
    'name', 'summary', 'storyline', 'url', 'video_urls', 'first_release_date',
    'aggregated_rating', 'category', 'status',
)
FIELD_LABELS = {
    'video_urls': 'Video URLs', 'first_release_date': 'Release date',
    'aggregated_rating': 'Aggregated rating', 'category': 'Release type',
}


def serialize_metadata_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (Category, Status)):
        return value.name
    return value


def values_match(left, right):
    return serialize_metadata_value(left) == serialize_metadata_value(right)


def mark_manual_changes(game, before):
    provenance = dict(game.metadata_provenance or {})
    changed_at = datetime.now(timezone.utc).isoformat()
    for field in EDITABLE_PROVIDER_FIELDS:
        if not values_match(before.get(field), getattr(game, field)):
            provenance[field] = {'source': 'manual', 'updated_at': changed_at}
    game.metadata_provenance = provenance


def merge_provider_metadata(game, metadata, provider='igdb'):
    """Apply provider values unless a field has an explicit manual override."""
    provenance = dict(game.metadata_provenance or {})
    candidates = dict(game.metadata_provider_values or {})
    changed_at = datetime.now(timezone.utc).isoformat()
    conflicts = []

    for field, value in metadata.items():
        if field not in PROVIDER_FIELDS:
            continue
        candidate = serialize_metadata_value(value)
        candidates[field] = {'provider': provider, 'value': candidate, 'updated_at': changed_at}
        if provenance.get(field, {}).get('source') == 'manual':
            if not values_match(getattr(game, field), value):
                conflicts.append(field)
            continue
        setattr(game, field, value)
        provenance[field] = {'source': provider, 'updated_at': changed_at}

    game.metadata_provenance = provenance
    game.metadata_provider_values = candidates
    return conflicts


def apply_provider_candidate(game, field):
    if field not in PROVIDER_FIELDS:
        raise ValueError('Unsupported metadata field')
    candidate = (game.metadata_provider_values or {}).get(field)
    if not candidate:
        raise ValueError('No provider value is available for this field')
    value = candidate.get('value')
    if field == 'first_release_date' and value:
        value = datetime.fromisoformat(value)
    elif field == 'category' and value:
        value = Category[value]
    elif field == 'status' and value:
        value = Status[value]
    setattr(game, field, value)
    provenance = dict(game.metadata_provenance or {})
    provenance[field] = {
        'source': candidate.get('provider', 'provider'),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    game.metadata_provenance = provenance


def metadata_conflicts(game):
    conflicts = []
    for field, candidate in (game.metadata_provider_values or {}).items():
        if field not in PROVIDER_FIELDS:
            continue
        if (game.metadata_provenance or {}).get(field, {}).get('source') != 'manual':
            continue
        if values_match(getattr(game, field), candidate.get('value')):
            continue
        conflicts.append({
            'field': field,
            'label': FIELD_LABELS.get(field, field.replace('_', ' ').title()),
            'manual_value': serialize_metadata_value(getattr(game, field)),
            'provider_value': candidate.get('value'),
            'provider': candidate.get('provider', 'provider').upper(),
        })
    return conflicts
