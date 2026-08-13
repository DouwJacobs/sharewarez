from datetime import datetime, timezone
from types import SimpleNamespace

from sharewarez.models import Category, Status
from sharewarez.utils.metadata_provenance import (
    apply_provider_candidate,
    mark_manual_changes,
    merge_provider_metadata,
    metadata_conflicts,
)


def make_game(**overrides):
    values = {
        'name': 'Manual name', 'summary': 'Manual summary', 'storyline': None,
        'url': None, 'video_urls': None, 'first_release_date': None,
        'aggregated_rating': None, 'aggregated_rating_count': None,
        'rating': None, 'rating_count': None, 'total_rating': None,
        'total_rating_count': None, 'category': Category.MAIN_GAME,
        'status': Status.RELEASED, 'metadata_provenance': {},
        'metadata_provider_values': {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_provider_refresh_preserves_manual_value_and_records_conflict():
    game = make_game(metadata_provenance={'name': {'source': 'manual'}})

    conflicts = merge_provider_metadata(game, {'name': 'Provider name', 'rating': 88})

    assert game.name == 'Manual name'
    assert game.rating == 88
    assert conflicts == ['name']
    assert game.metadata_provider_values['name']['value'] == 'Provider name'
    assert game.metadata_provenance['rating']['source'] == 'igdb'


def test_manual_change_is_marked_without_claiming_unchanged_fields():
    game = make_game(name='Edited name')
    before = {field: getattr(make_game(), field) for field in (
        'name', 'summary', 'storyline', 'url', 'video_urls',
        'first_release_date', 'aggregated_rating', 'category', 'status',
    )}

    mark_manual_changes(game, before)

    assert game.metadata_provenance['name']['source'] == 'manual'
    assert 'summary' not in game.metadata_provenance


def test_applying_provider_candidate_resolves_conflict():
    game = make_game(
        metadata_provenance={'category': {'source': 'manual'}},
        metadata_provider_values={
            'category': {'provider': 'igdb', 'value': 'REMAKE', 'updated_at': 'now'},
        },
    )

    assert metadata_conflicts(game)[0]['field'] == 'category'
    apply_provider_candidate(game, 'category')

    assert game.category is Category.REMAKE
    assert game.metadata_provenance['category']['source'] == 'igdb'
    assert metadata_conflicts(game) == []


def test_datetime_candidates_round_trip():
    release_date = datetime(2026, 8, 13, tzinfo=timezone.utc)
    game = make_game(metadata_provider_values={
        'first_release_date': {
            'provider': 'igdb', 'value': release_date.isoformat(), 'updated_at': 'now',
        },
    })

    apply_provider_candidate(game, 'first_release_date')

    assert game.first_release_date == release_date
