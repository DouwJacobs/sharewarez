from dataclasses import dataclass

from sharewarez.utils.metadata_provider_igdb import IGDBMetadataProvider
from sharewarez.utils.metadata_providers import (
    normalize_provider_order,
    search_metadata_games,
)


@dataclass
class StubProvider:
    name: str
    results: list
    error: str | None = None
    raises: bool = False

    def search_games(self, term):
        if self.raises:
            raise RuntimeError('credential detail must not escape')
        return self.results, self.error


def test_provider_order_is_normalized_and_keeps_available_fallbacks():
    assert normalize_provider_order(
        [' SECONDARY ', 'unknown', 'secondary'],
        ['igdb', 'secondary'],
    ) == ('secondary', 'igdb')


def test_search_advances_to_next_provider_after_failure():
    providers = {
        'igdb': StubProvider('igdb', [], 'temporarily unavailable'),
        'secondary': StubProvider('secondary', [{'game_name': 'Fallback game'}]),
    }

    outcome = search_metadata_games(
        'Fallback game', providers, configured_order=('igdb', 'secondary'),
    )

    assert outcome.results == [{'game_name': 'Fallback game'}]
    assert outcome.provider == 'secondary'
    assert outcome.error is None


def test_search_returns_safe_errors_when_every_provider_fails():
    outcome = search_metadata_games(
        'Unavailable game',
        {'igdb': StubProvider('igdb', [], raises=True)},
    )

    assert outcome.results == []
    assert outcome.provider is None
    assert outcome.error == 'IGDB: provider request failed'
    assert 'credential detail' not in outcome.error


def test_igdb_adapter_uses_api_endpoint_and_normalizes_results():
    calls = []

    def request(endpoint, query):
        calls.append((endpoint, query))
        return [{
            'id': 282831,
            'name': 'The Blood of Dawnwalker',
            'cover': {'image_id': 'cover-id'},
            'platforms': [{'name': 'PC'}],
        }]

    results, error = IGDBMetadataProvider(request=request).search_games('Dawnwalker')

    assert error is None
    assert results[0]['igdb_id'] == 282831
    assert results[0]['game_name'] == 'The Blood of Dawnwalker'
    assert results[0]['cover_url'].endswith('/cover-id.jpg')
    assert calls[0][0] == 'https://api.igdb.com/v4/games'
    assert 'search "Dawnwalker"' in calls[0][1]
