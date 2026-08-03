from unittest.mock import patch

from sharewarez.utilities import _scan_enabled_supplemental_content


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
