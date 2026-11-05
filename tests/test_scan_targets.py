from unittest.mock import patch

from flask import Flask
import pytest

from sharewarez.utils.incremental_scanning import filesystem_fingerprint
from sharewarez.utils.scan_targets import (
    ScanTargetError, enumerate_scan_target, legacy_scan_options,
    resolve_scan_target, validate_scan_options,
)


@pytest.fixture
def storage(tmp_path):
    app = Flask(__name__)
    active = tmp_path / 'active'
    legacy = tmp_path / 'legacy'
    active.mkdir()
    legacy.mkdir()
    app.config.update(BASE_FOLDER_POSIX=str(active), BASE_FOLDER_WINDOWS=str(active), DATA_FOLDER_WAREZ=str(legacy))
    with app.app_context():
        yield active, legacy


def test_relative_and_legacy_absolute_paths_share_one_authority(storage):
    active, legacy = storage
    (active / 'games').mkdir()
    assert resolve_scan_target('games').path == str(active / 'games')
    assert resolve_scan_target('.').path == str(active)
    assert resolve_scan_target(str(legacy)).path == str(legacy)
    with pytest.raises(ScanTargetError):
        resolve_scan_target('../legacy')
    with pytest.raises(ScanTargetError):
        resolve_scan_target(str(legacy), active_root_only=True)


def test_file_targets_require_supported_files_mode(storage):
    active, _ = storage
    game = active / 'game.iso'
    game.write_bytes(b'game')
    with pytest.raises(ScanTargetError, match='Folders mode'):
        resolve_scan_target('game.iso')
    with pytest.raises(ScanTargetError, match='file type'):
        resolve_scan_target('game.iso', 'files', extensions=['zip'])
    target = resolve_scan_target('game.iso', 'files', extensions=['iso'])
    candidates, complete = enumerate_scan_target(target, ['iso'], [], [])
    assert complete and [item['full_path'] for item in candidates] == [str(game)]
    assert target.owns_stored_path(str(game))
    assert not target.owns_stored_path(str(active / 'other.iso'))


def test_direct_children_and_missing_history_are_conservative(storage):
    active, _ = storage
    target = resolve_scan_target('.')
    assert target.owns_stored_path(str(active / 'Missing'))
    assert not target.owns_stored_path(str(active / 'nested' / 'Missing'))
    assert not target.owns_stored_path('Missing')
    assert not target.owns_stored_path(None)


def test_child_link_retargeting_and_broken_links_invalidate_enumeration(storage):
    active, legacy = storage
    (active / 'Good').mkdir()
    (active / 'internal').symlink_to(active / 'Good', target_is_directory=True)
    target = resolve_scan_target('.')
    candidates, complete = enumerate_scan_target(target, [], [], [])
    assert complete and len(candidates) == 2
    (active / 'internal').unlink()
    (active / 'internal').symlink_to(legacy, target_is_directory=True)
    (active / 'broken').symlink_to(active / 'absent')
    candidates, complete = enumerate_scan_target(target, [], [], [])
    assert not complete and [item['name'] for item in candidates] == ['Good']
    assert not target.owns_stored_path(str(active / 'internal'))


def test_fingerprint_supports_single_file_and_changes(storage):
    active, _ = storage
    path = active / 'game.iso'
    path.write_bytes(b'first')
    first, count, size = filesystem_fingerprint(str(path))
    assert (count, size) == (1, 5)
    path.write_bytes(b'changed')
    assert filesystem_fingerprint(str(path))[0] != first


@pytest.mark.parametrize('fault', ['walk', 'stat', 'broken', 'escape'])
def test_fingerprint_never_certifies_an_incomplete_tree(storage, fault):
    active, legacy = storage
    game = active / 'game.iso'
    game.write_bytes(b'game')
    if fault in {'broken', 'escape'}:
        (active / 'link').symlink_to(active / 'absent' if fault == 'broken' else legacy)
        with pytest.raises(OSError):
            filesystem_fingerprint(str(active))
    elif fault == 'walk':
        def walk(path, onerror):
            onerror(PermissionError('unreadable nested directory'))
            return iter(())
        with patch('sharewarez.utils.incremental_scanning.os.walk', side_effect=walk), pytest.raises(PermissionError):
            filesystem_fingerprint(str(active))
    else:
        import os
        original = os.stat
        def inspect(path, *args, **kwargs):
            if path == str(game):
                raise OSError('failed child stat')
            return original(path, *args, **kwargs)
        with patch('sharewarez.utils.incremental_scanning.os.stat', side_effect=inspect), pytest.raises(OSError):
            filesystem_fingerprint(str(active))


@pytest.mark.parametrize('options', [None, [], True, 'yes', {'folder_path': '/unsafe'}, {'remove_missing': 1}, {'fetch_hltb': 'false'}])
def test_new_options_are_strict_while_legacy_options_are_sanitized(options):
    with pytest.raises(ValueError):
        validate_scan_options(options)
    safe, discarded = legacy_scan_options(options)
    assert discarded and safe == {}


def test_supported_options_preserve_false():
    assert validate_scan_options({'remove_missing': False, 'fetch_hltb': True}) == {'remove_missing': False, 'fetch_hltb': True}


def test_manual_write_probe_does_not_follow_child_links(storage):
    active, legacy = storage
    (active / 'internal').mkdir()
    (active / 'escape').symlink_to(legacy, target_is_directory=True)
    from sharewarez.utils.local_metadata import check_library_write_permissions
    with patch('sharewarez.utils.local_metadata.check_write_permissions', return_value=(True, None)) as probe:
        assert check_library_write_permissions(str(active)) == (True, [])
    assert {call.args[0] for call in probe.call_args_list} == {str(active), str(active / 'internal')}
