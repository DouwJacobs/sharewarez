"""Real storage boundaries and destructive reconciliation regressions."""
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from sharewarez.models import AllowedFileType, Game, GameUpdate, GlobalSettings, Library, ScanJob
from sharewarez.platform import LibraryPlatform
from sharewarez.utilities import scan_and_add_games


@pytest.fixture
def scan_storage(app, db_session, tmp_path):
    app.config.update(BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path), DATA_FOLDER_WAREZ=str(tmp_path))
    library = Library(name=f'Safety {uuid4().hex}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    settings = db_session.execute(select(GlobalSettings)).scalars().first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.scan_thread_count = 1
    settings.enable_game_updates = False
    settings.enable_game_extras = False
    settings.write_local_metadata = False
    if not db_session.query(AllowedFileType).filter_by(value='iso').first():
        db_session.add(AllowedFileType(value='iso'))
    db_session.commit()
    with patch('sharewarez.utilities.is_scan_job_running', return_value=False):
        yield library, tmp_path


def test_scan_root_a_never_removes_missing_games_in_root_b(scan_storage, db_session):
    library, root = scan_storage
    a = root / 'a'
    a.mkdir()
    (a / 'Present').mkdir()
    paths = [a / 'Present', a / 'Missing', root / 'offline-b' / 'Missing', a / 'nested' / 'Missing']
    games = [Game(name=f'Game {i}', library_uuid=library.uuid, full_disk_path=str(path)) for i, path in enumerate(paths)]
    games.append(Game(name='No historical path', library_uuid=library.uuid, full_disk_path=None))
    db_session.add_all(games)
    db_session.commit()
    expected = games[1].uuid
    with patch('sharewarez.utilities.remove_from_lib', return_value=True) as remove:
        scan_and_add_games(str(a), library_uuid=library.uuid, remove_missing=True)
    assert [call.args[0] for call in remove.call_args_list] == [expected]


@pytest.mark.parametrize('fault', ['empty', 'broken', 'escape', 'processing', 'cancel', 'nested_permission', 'shutdown'])
def test_incomplete_or_failed_scan_never_removes(scan_storage, db_session, fault):
    library, root = scan_storage
    target = root / 'target'
    target.mkdir()
    if fault != 'empty':
        (target / 'Present').mkdir()
    if fault == 'broken':
        (target / 'broken').symlink_to(target / 'absent')
    if fault == 'escape':
        (target / 'escape').symlink_to(root, target_is_directory=True)
    db_session.add(Game(name='Missing', library_uuid=library.uuid, full_disk_path=str(target / 'Missing')))
    db_session.commit()

    def process(*args, **kwargs):
        if fault == 'processing':
            raise OSError('fixture persistence failure')
        if fault == 'cancel':
            job = db_session.execute(select(ScanJob).where(ScanJob.library_uuid == library.uuid)).scalar_one()
            job.is_enabled = False
            db_session.commit()
        return True

    from sharewarez.utils.incremental_scanning import filesystem_fingerprint
    with (
        patch('sharewarez.utilities.process_game_with_fallback', side_effect=process),
        patch('sharewarez.utilities.remove_from_lib') as remove,
        patch('sharewarez.utils.shutdown.should_continue_processing', return_value=fault != 'shutdown'),
        patch('sharewarez.utilities.filesystem_fingerprint', side_effect=PermissionError('nested unreadable') if fault == 'nested_permission' else filesystem_fingerprint),
    ):
        scan_and_add_games(str(target), library_uuid=library.uuid, remove_missing=True)
    remove.assert_not_called()
    job = db_session.execute(select(ScanJob).where(ScanJob.library_uuid == library.uuid)).scalar_one()
    assert 'No removals performed' in job.error_message


def test_actual_deletion_preserves_other_root_and_related_records(scan_storage, db_session):
    library, root = scan_storage
    (root / 'Present').mkdir()
    missing = Game(name='Delete only this', library_uuid=library.uuid, full_disk_path=str(root / 'Missing'))
    other = Game(name='Offline elsewhere', library_uuid=library.uuid, full_disk_path=str(root.parent / 'offline' / 'Missing'))
    db_session.add_all([Game(name='Present', library_uuid=library.uuid, full_disk_path=str(root / 'Present')), missing, other])
    db_session.flush()
    missing_id, other_id = missing.uuid, other.uuid
    db_session.add_all([GameUpdate(game_uuid=missing_id, file_path='/synthetic/deleted-update'), GameUpdate(game_uuid=other_id, file_path='/synthetic/retained-update')])
    db_session.commit()
    with patch('sharewarez.utils.game_core.delete_game_images'):
        scan_and_add_games(str(root), library_uuid=library.uuid, remove_missing=True)
    assert db_session.query(Game).filter_by(uuid=missing_id).first() is None
    assert db_session.query(Game).filter_by(uuid=other_id).one()
    assert db_session.query(GameUpdate).filter_by(game_uuid=missing_id).count() == 0
    assert db_session.query(GameUpdate).filter_by(game_uuid=other_id).count() == 1


@pytest.mark.parametrize('mode', ['folders', 'files'])
def test_cleanup_respects_selected_mode(scan_storage, db_session, mode):
    library, root = scan_storage
    (root / 'Present').mkdir()
    (root / 'present.iso').write_bytes(b'game')
    folder = Game(name='Missing folder', library_uuid=library.uuid, full_disk_path=str(root / 'Missing'))
    file = Game(name='Missing file', library_uuid=library.uuid, full_disk_path=str(root / 'missing.iso'), file_type='iso')
    db_session.add_all([folder, file])
    db_session.commit()
    with patch('sharewarez.utilities.process_game_with_fallback', return_value=True), patch('sharewarez.utilities.remove_from_lib', return_value=True) as remove:
        scan_and_add_games(str(root), scan_mode=mode, library_uuid=library.uuid, remove_missing=True)
    remove.assert_called_once_with(folder.uuid if mode == 'folders' else file.uuid)


def test_single_file_scan_never_reconciles_sibling_files(scan_storage, db_session):
    library, root = scan_storage
    path = root / 'one.iso'
    path.write_bytes(b'one')
    db_session.add_all([
        Game(name='One', library_uuid=library.uuid, full_disk_path=str(path)),
        Game(name='Missing sibling', library_uuid=library.uuid, full_disk_path=str(root / 'two.iso')),
    ])
    db_session.commit()
    with patch('sharewarez.utilities.remove_from_lib') as remove:
        scan_and_add_games(str(path), scan_mode='files', library_uuid=library.uuid, remove_missing=True)
    remove.assert_not_called()
    job = db_session.execute(select(ScanJob).where(ScanJob.library_uuid == library.uuid)).scalar_one()
    assert job.status == 'Completed' and job.total_folders == 1
