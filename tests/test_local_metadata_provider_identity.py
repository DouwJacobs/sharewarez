import json
from unittest.mock import patch

from sharewarez.utils.local_metadata import read_local_metadata, write_local_metadata


def _allow_local_path():
    return patch.multiple(
        'sharewarez.utils.local_metadata',
        get_allowed_base_directories=lambda _app: ['/'],
        is_safe_path=lambda _path, _bases: (True, None),
    )


def test_legacy_igdb_metadata_is_normalized(app, tmp_path):
    (tmp_path / 'sharewarez.json').write_text(
        json.dumps({'igdb_id': 7331, 'metadata_version': '1.0'}),
        encoding='utf-8',
    )

    with app.app_context(), _allow_local_path():
        metadata = read_local_metadata(str(tmp_path))

    assert metadata['identity'] == {'provider': 'igdb', 'external_id': '7331'}
    assert metadata['metadata_provider'] == 'igdb'
    assert metadata['provider_game_id'] == '7331'


def test_provider_neutral_metadata_round_trip(app, tmp_path):
    with app.app_context(), _allow_local_path():
        assert write_local_metadata(
            str(tmp_path),
            provider='rawg',
            external_id='3498',
            provider_url='https://rawg.io/games/grand-theft-auto-v',
            game_title='Grand Theft Auto V',
        )
        metadata = read_local_metadata(str(tmp_path))

    assert metadata['metadata_version'] == '2.0'
    assert metadata['identity'] == {
        'provider': 'rawg',
        'external_id': '3498',
        'provider_url': 'https://rawg.io/games/grand-theft-auto-v',
    }
    assert 'igdb_id' not in metadata


def test_new_igdb_metadata_keeps_legacy_key(app, tmp_path):
    with app.app_context(), _allow_local_path():
        assert write_local_metadata(str(tmp_path), igdb_id=7331)

    payload = json.loads((tmp_path / 'sharewarez.json').read_text(encoding='utf-8'))
    assert payload['identity'] == {'provider': 'igdb', 'external_id': '7331'}
    assert payload['igdb_id'] == 7331
