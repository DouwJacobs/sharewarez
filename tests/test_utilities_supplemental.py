from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from sharewarez.utilities import (
    _scan_enabled_supplemental_content,
    refresh_game_metadata_and_updates,
)


def test_enabled_updates_are_scanned_for_existing_game():
    with patch('sharewarez.utilities.os.path.isdir', return_value=True), \
         patch('sharewarez.utilities.process_game_updates') as scan_updates, \
         patch('sharewarez.utilities.process_game_extras') as scan_extras:
        _scan_enabled_supplemental_content(
            'Game', '/storage/Repacks/Game', 'library-uuid',
            True, 'updates', False, 'extras'
        )

    scan_updates.assert_called_once_with(
        'Game', '/storage/Repacks/Game',
        '/storage/Repacks/Game/updates', 'library-uuid', 'updates'
    )
    scan_extras.assert_not_called()


def test_disabled_supplemental_scans_do_not_touch_disk_processors():
    with patch('sharewarez.utilities.process_game_updates') as scan_updates, \
         patch('sharewarez.utilities.process_game_extras') as scan_extras:
        _scan_enabled_supplemental_content(
            'Game', '/storage/Repacks/Game', 'library-uuid',
            False, 'updates', False, 'extras'
        )

    scan_updates.assert_not_called()
    scan_extras.assert_not_called()


def test_metadata_refresh_updates_igdb_fields_and_repairs_developer_placeholder():
    game = SimpleNamespace(
        uuid='game-uuid', igdb_id=123, name='Old name', full_disk_path='/games/Game',
        library_uuid='library-uuid', developer=SimpleNamespace(name='<Developer 6>'),
        publisher=None, genres=[], themes=[], game_modes=[], platforms=[],
        player_perspectives=[], metadata_provenance={}, metadata_provider_values={},
    )
    settings = SimpleNamespace(
        update_folder_name='updates', extras_folder_name='extras',
        enable_game_updates=False, enable_game_extras=False,
        enable_hltb_integration=False,
    )
    results = [
        SimpleNamespace(scalar_one_or_none=lambda: game),
        SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: settings)),
    ]
    metadata = {
        'name': 'Updated name',
        'rating': 84.5,
        'aggregated_rating': 79.25,
        'first_release_date': 1704067200,
        'genres': [{'name': 'Adventure'}],
        'involved_companies': [99],
    }

    def assign_company(refreshed_game, _igdb_id, _company_ids):
        refreshed_game.developer = SimpleNamespace(name='Actual Developer')

    app = Flask(__name__)
    with app.app_context(), \
         patch('sharewarez.utilities.db.session.execute', side_effect=results), \
         patch('sharewarez.utilities.db.session.commit'), \
         patch('sharewarez.utilities.os.path.exists', return_value=True), \
         patch('sharewarez.utilities.os.path.isdir', return_value=True), \
         patch('sharewarez.utilities.get_allowed_base_directories', return_value=['/games']), \
         patch('sharewarez.utilities.is_safe_path', return_value=(True, None)), \
         patch('sharewarez.utilities.fetch_game_by_igdb_id', return_value=[metadata]), \
         patch('sharewarez.utilities.get_or_create_entity', return_value='Adventure'), \
             patch('sharewarez.utilities.enumerate_companies', side_effect=assign_company), \
             patch('sharewarez.utils.game_relationships.sync_game_relationships'), \
             patch('sharewarez.utilities.read_first_nfo_content', return_value=None), \
         patch('sharewarez.utilities.get_folder_size_in_bytes_updates', return_value=1024), \
         patch('sharewarez.utilities._scan_enabled_supplemental_content'):
        refresh_result = refresh_game_metadata_and_updates(game.uuid)

    assert refresh_result.game_name == 'Updated name'
    assert refresh_result.filesystem_skipped is False
    assert game.rating == 84.5
    assert game.aggregated_rating == 79.25
    assert game.first_release_date.year == 2024
    assert game.developer.name == 'Actual Developer'
    assert game.genres == ['Adventure']


def test_metadata_refresh_succeeds_when_game_path_is_unavailable():
    game = SimpleNamespace(
        uuid='game-uuid', igdb_id=123, name='Old name', full_disk_path='/storage/offline/Game',
        library_uuid='library-uuid', developer=None, publisher=None, genres=[], themes=[],
        game_modes=[], platforms=[], player_perspectives=[], metadata_provenance={},
        metadata_provider_values={},
        nfo_content='Existing NFO', size=2048,
    )
    settings = SimpleNamespace(
        update_folder_name='updates', extras_folder_name='extras',
        enable_game_updates=True, enable_game_extras=True, enable_hltb_integration=True,
    )
    results = [
        SimpleNamespace(scalar_one_or_none=lambda: game),
        SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: settings)),
    ]

    app = Flask(__name__)
    with app.app_context(), \
         patch('sharewarez.utilities.db.session.execute', side_effect=results), \
         patch('sharewarez.utilities.db.session.commit'), \
         patch('sharewarez.utilities.os.path.isdir', return_value=False), \
             patch('sharewarez.utilities.fetch_game_by_igdb_id', return_value=[{'name': 'Updated name'}]), \
             patch('sharewarez.utils.game_relationships.sync_game_relationships'), \
             patch('sharewarez.utilities.read_first_nfo_content') as read_nfo, \
         patch('sharewarez.utilities.get_folder_size_in_bytes_updates') as calculate_size, \
         patch('sharewarez.utilities._scan_enabled_supplemental_content') as scan_supplemental, \
         patch('sharewarez.utils.hltb.update_game_hltb_sync') as refresh_hltb:
        refresh_result = refresh_game_metadata_and_updates(game.uuid)

    assert refresh_result.game_name == 'Updated name'
    assert refresh_result.filesystem_skipped is True
    assert '/storage/offline/Game' in refresh_result.filesystem_message
    assert game.nfo_content == 'Existing NFO'
    assert game.size == 2048
    read_nfo.assert_not_called()
    calculate_size.assert_not_called()
    scan_supplemental.assert_not_called()
    refresh_hltb.assert_called_once_with(game.uuid, 'Updated name')
