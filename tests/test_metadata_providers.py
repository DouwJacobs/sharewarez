from dataclasses import dataclass

from sharewarez.utils.metadata_provider_igdb import IGDBMetadataProvider
from sharewarez.utils.metadata_providers import (
    available_provider_names,
    configured_provider_order,
    normalize_provider_order,
    search_metadata_games,
    validate_provider_order,
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


@dataclass
class StubSettings:
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
    rawg_api_key: str | None = None
    rawg_enabled: bool = False
    metadata_provider_order: list | None = None


def test_provider_order_is_normalized_and_keeps_available_fallbacks():
    assert normalize_provider_order(
        [' SECONDARY ', 'unknown', 'secondary'],
        ['igdb', 'secondary'],
    ) == ('secondary', 'igdb')


def test_operator_provider_order_validation_is_strict():
    assert validate_provider_order([' RAWG ', 'igdb']) == ('rawg', 'igdb')
    for invalid in (None, [], ['unknown'], ['igdb', 'IGDB']):
        try:
            validate_provider_order(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Expected provider order rejection for {invalid!r}')


def test_configured_order_uses_only_enabled_credentialed_providers():
    settings = StubSettings(
        igdb_client_id='client',
        igdb_client_secret='secret',
        rawg_api_key='rawg-key',
        rawg_enabled=True,
        metadata_provider_order=['rawg', 'igdb'],
    )

    assert available_provider_names(settings) == ('igdb', 'rawg')
    assert configured_provider_order(settings) == ('rawg', 'igdb')


def test_disabled_rawg_is_not_available_even_when_key_is_stored():
    settings = StubSettings(
        rawg_api_key='rawg-key',
        rawg_enabled=False,
        metadata_provider_order=['rawg', 'igdb'],
    )

    assert available_provider_names(settings) == ()
    assert configured_provider_order(settings) == ()


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


def test_igdb_media_merges_linked_artwork_with_direct_api_logos():
    calls = []

    def request(endpoint, query):
        calls.append((endpoint, query))
        if endpoint.endswith('/games'):
            return [{
                'id': 282831,
                'cover': 100,
                'screenshots': [200],
                'artworks': [300],
            }]
        return [{
            'id': 400,
            'url': '//images.igdb.com/logo.png',
            'image_type': {'name': 'Game logo (color)'},
        }]

    media, error = IGDBMetadataProvider(request=request).fetch_media(282831)

    assert error is None
    assert media['cover'] == 100
    assert media['screenshots'] == [200]
    assert media['artworks'] == [300, {
        'id': 400,
        'url': '//images.igdb.com/logo.png',
        'image_type': {'name': 'Game logo (color)'},
    }]
    assert [endpoint.rsplit('/', 1)[-1] for endpoint, _query in calls] == [
        'games', 'artworks',
    ]
    assert 'where game = 282831' in calls[1][1]


def test_igdb_full_payload_lookup_owns_endpoint_and_query():
    calls = []

    def request(endpoint, query):
        calls.append((endpoint, query))
        return [{'id': 282831, 'name': 'The Blood of Dawnwalker'}]

    provider = IGDBMetadataProvider(request=request)
    payload, fetch_error = provider.fetch_game_payload(282831)
    results, search_error = provider.search_game_payloads(
        'Dawnwalker', platform_id=6, limit=1,
    )

    assert fetch_error is None and search_error is None
    assert payload['id'] == 282831
    assert results[0]['name'] == 'The Blood of Dawnwalker'
    assert all(endpoint == 'https://api.igdb.com/v4/games' for endpoint, _ in calls)
    assert 'where id = 282831; limit 1;' in calls[0][1]
    assert 'cover.id' in calls[0][1]
    assert 'screenshots.id' in calls[0][1]
    assert 'artworks.id' in calls[0][1]
    assert 'search "Dawnwalker"; where platforms = (6); limit 1;' in calls[1][1]


def test_igdb_supporting_lookups_stay_on_documented_api_endpoints():
    calls = []

    def request(endpoint, query):
        calls.append((endpoint, query))
        if endpoint.endswith('/covers'):
            return [{'url': '//images.igdb.com/cover.jpg'}]
        if endpoint.endswith('/websites'):
            return [{'url': 'https://example.test', 'category': 1}]
        return [{'company': {'name': 'Studio'}, 'developer': True}]

    provider = IGDBMetadataProvider(request=request)
    image, image_error = provider.fetch_image_record('cover', 100)
    websites, websites_error = provider.fetch_websites(282831)
    companies, companies_error = provider.fetch_involved_companies(282831, [10, 20])

    assert image_error is None and image['url'].endswith('cover.jpg')
    assert websites_error is None and websites[0]['category'] == 1
    assert companies_error is None and companies[0]['developer'] is True
    assert [endpoint.rsplit('/', 1)[-1] for endpoint, _query in calls] == [
        'covers', 'websites', 'involved_companies',
    ]
    assert 'where id=100' in calls[0][1]
    assert 'where game=282831' in calls[1][1]
    assert 'id=(10,20)' in calls[2][1]
