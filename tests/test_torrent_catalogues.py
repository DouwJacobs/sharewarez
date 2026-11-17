"""Offline catalogue parsing, conservative matching and outbound safety checks."""
import json
from unittest.mock import Mock, patch

import pytest

from sharewarez.utils import torrent_catalogues as service


MAGNET = 'magnet:?xt=urn:btih:' + 'a' * 40


def catalogue(*titles):
    return service.parse_catalogue({'name': 'Public releases', 'downloads': [
        {'title': title, 'uris': [MAGNET], 'uploadDate': '2026-01-01', 'fileSize': '1 GB'}
        for title in titles
    ]})


def test_hydra_shape_and_supported_uri_filtering():
    value = service.parse_catalogue(json.dumps({'name': 'Example', 'downloads': [
        {'title': 'A Game', 'uris': [MAGNET, 'https://example.com/a.torrent', 'https://example.com/archive.zip']}
    ]}).encode())
    assert value['downloads'][0]['uris'] == [MAGNET, 'https://example.com/a.torrent']
    assert service.parse_catalogue({'name': 'Empty', 'downloads': []})['downloads'] == []


@pytest.mark.parametrize('payload', [b'<html>Verify</html>', {}, {'name': 'X', 'downloads': {}},
    {'name': 'X', 'downloads': [{'title': 'X', 'uris': 'bad'}]},
    {'name': 'X', 'downloads': [{'title': 'X', 'uris': [123]}]}])
def test_reject_invalid_catalogues(payload):
    with pytest.raises(service.CatalogueError):
        service.parse_catalogue(payload)


@pytest.mark.parametrize('release', ['A Game', 'A Game [FitGirl Repack]',
                                  'A Game – v1.2.3 [FitGirl Repack]'])
def test_explicit_release_suffixes_match(release):
    assert service.match_catalogues('A Game', [catalogue(release)])['status'] == 'matched'


@pytest.mark.parametrize('other', ['A Game 2', 'A Game Remastered', 'A Game Gold Edition',
                                  'A Game: Expansion', 'A Game + DLC',
                                  'A Game – v1.2 Gold Edition', 'A Game (v1.2 Remastered)'])
def test_meaningful_title_words_are_preserved(other):
    assert service.match_catalogues('A Game', [catalogue(other)])['status'] == 'not_found'


def test_multiple_releases_are_ambiguous_and_duplicate_catalogues_are_not():
    assert service.match_catalogues('A Game', [catalogue('A Game – v1.2', 'A Game – v1.3')])['status'] == 'ambiguous'
    source = catalogue('A Game')
    assert service.match_catalogues('A Game', [source, source])['status'] == 'matched'


def test_catalogue_alias_and_selective_download_label_match_complete_title():
    source = catalogue('Grand Theft Auto V / GTA 5 (v1.0.2802/1.64 Online, MULTi13) [FitGirl Repack]')
    assert service.match_catalogues('Grand Theft Auto V', [source])['status'] == 'matched'
    assert service.match_catalogues('GTA 5', [source])['status'] == 'matched'
    source = catalogue('Grand Theft Auto V (v1.0.3095/1.68 + NVE Platinum Modpack, MULTi13) [FitGirl Repack, Selective Download - from 49.2 GB]')
    assert service.match_catalogues('Grand Theft Auto V', [source])['status'] == 'matched'


def test_edition_title_with_version_matches_only_that_edition():
    source = catalogue('A Game: Gold Edition – v1.2 [FitGirl Repack]')
    assert service.match_catalogues('A Game: Gold Edition', [source])['status'] == 'matched'
    assert service.match_catalogues('A Game', [source])['status'] == 'not_found'


def test_aliases_do_not_choose_between_releases():
    result = service.match_catalogues('Grand Theft Auto V', [catalogue(
        'Grand Theft Auto V / GTA 5 – v1.0.3411/1.70 + NVE Platinum Modpack',
        'Grand Theft Auto V (v1.0.3095/1.68) [FitGirl Repack]')])
    assert result['status'] == 'ambiguous'
    assert len(result['candidates']) == 2


def dated_releases(*dates):
    source = catalogue(*(f'A Game – v1.{index}' for index in range(len(dates))))
    for entry, date in zip(source['downloads'], dates):
        entry['uploadDate'] = date
    return source


def test_latest_upload_policy_is_opt_in_and_compares_actual_timestamps():
    source = dated_releases('2026-01-01T10:00:00+02:00', '2026-01-01T09:00:00Z')
    assert service.match_catalogues('A Game', [source])['status'] == 'ambiguous'
    result = service.match_catalogues('A Game', [source], prefer_latest_upload=True)
    assert result['entry']['title'] == 'A Game – v1.1'
    assert result['selection_reason'] == 'latest_upload'


@pytest.mark.parametrize('dates', [
    ('2026-01-01', ''), ('2026-01-01', None), ('2026-01-01', 'invalid'),
    ('2026-01-01T10:00:00+02:00', '2026-01-01T08:00:00Z'),
])
def test_latest_upload_keeps_missing_invalid_and_tied_dates_for_review(dates):
    result = service.match_catalogues('A Game', [dated_releases(*dates)], prefer_latest_upload=True)
    assert result['status'] == 'ambiguous'


def test_latest_upload_considers_all_matches_before_candidate_display_limit():
    dates = [f'2026-01-{index:02d}' for index in range(1, 13)]
    result = service.match_catalogues('A Game', [dated_releases(*dates)], prefer_latest_upload=True)
    assert result['entry']['title'] == 'A Game – v1.11'


@pytest.mark.parametrize('url', ['file:///tmp/a', 'https://user:secret@example.com/a',
                               'http://example.com:99999/a', 'https://example.com/a#fragment',
                               'https://example.com/\nsecret'])
def test_invalid_url_syntax(url):
    with pytest.raises(service.CatalogueError):
        service.validate_catalogue_url(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.2', '169.254.169.254', '::1', '::ffff:127.0.0.1'])
def test_private_addresses_never_open_connections(address):
    with patch.object(service.socket, 'getaddrinfo', return_value=[(None, None, None, None, (address, 443))]), \
         patch.object(service.urllib3, 'HTTPSConnectionPool') as pool:
        with pytest.raises(service.CatalogueError):
            service.fetch_bytes('https://example.com/catalogue.json', 1024)
        pool.assert_not_called()


def response(body=b'{}', status=200, headers=None):
    result = Mock(status=status, headers=headers or {})
    result.read.side_effect = [body, b'']
    return result


def test_connection_pins_ip_but_verifies_original_hostname():
    reply = response()
    with patch.object(service, '_public_addresses', return_value=['93.184.216.34']), \
         patch.object(service.urllib3, 'HTTPSConnectionPool') as pool:
        pool.return_value.urlopen.return_value = reply
        assert service.fetch_bytes('https://example.com/a', 10) == b'{}'
        assert pool.call_args.args == ('93.184.216.34',)
        assert pool.call_args.kwargs['assert_hostname'] == 'example.com'
        assert pool.call_args.kwargs['server_hostname'] == 'example.com'
        assert pool.return_value.urlopen.call_args.kwargs['headers']['Host'] == 'example.com'
        assert pool.return_value.urlopen.call_args.kwargs['redirect'] is False
        reply.close.assert_called_once()


def test_redirect_rechecks_public_destination():
    with patch.object(service, '_public_addresses', side_effect=[['93.184.216.34'], service.CatalogueError('private')]), \
         patch.object(service.urllib3, 'HTTPSConnectionPool') as pool:
        pool.return_value.urlopen.return_value = response(status=302, headers={'Location': 'http://127.0.0.1/a'})
        with pytest.raises(service.CatalogueError):
            service.fetch_bytes('https://example.com/a', 10)
        assert pool.call_count == 1


def test_oversized_response_is_closed():
    reply = response(body=b'123456')
    with patch.object(service, '_public_addresses', return_value=['93.184.216.34']), \
         patch.object(service.urllib3, 'HTTPSConnectionPool') as pool:
        pool.return_value.urlopen.return_value = reply
        with pytest.raises(service.CatalogueError, match='size'):
            service.fetch_bytes('https://example.com/a', 5)
        reply.close.assert_called_once()


def test_cache_force_refresh_and_mutation_isolation():
    service._cache.clear()
    body = json.dumps({'name': 'Test', 'downloads': []}).encode()
    with patch.object(service, 'fetch_bytes', return_value=body) as fetch:
        first = service.fetch_catalogue('https://example.com/source.json')
        first['downloads'].append({'bad': True})
        assert service.fetch_catalogue('https://example.com/source.json')['downloads'] == []
        assert fetch.call_count == 1
        service.fetch_catalogue('https://example.com/source.json', force_refresh=True)
        assert fetch.call_count == 2
    service._cache.clear()


def test_invalid_magnets_cannot_be_selected_as_the_newest_release():
    source = service.parse_catalogue({'name': 'Test', 'downloads': [
        {'title': 'A Game – v1.0', 'uris': [MAGNET], 'uploadDate': '2025-01-01'},
        {'title': 'A Game – v1.1', 'uris': ['magnet:?xt=bad'], 'uploadDate': '2026-01-01'},
    ]})
    result = service.match_catalogues('A Game', [source], prefer_latest_upload=True)
    assert result['entry']['title'] == 'A Game – v1.0'


def test_duplicate_source_order_does_not_change_latest_upload_selection():
    first = dated_releases('2025-01-01', '2025-06-01')
    mirror = dated_releases('2026-01-01')
    for sources in ([first, mirror], [mirror, first]):
        result = service.match_catalogues('A Game', sources, prefer_latest_upload=True)
        assert result['entry']['title'] == 'A Game – v1.0'


def test_malformed_idna_hostname_is_a_friendly_catalogue_error():
    with pytest.raises(service.CatalogueError):
        service.validate_catalogue_url('https://' + 'a' * 64 + '.example/catalogue.json')
