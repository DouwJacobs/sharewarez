import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock, call, ANY
from uuid import uuid4
from datetime import datetime, timedelta
from threading import Thread
import time

from sharewarez import create_app, db
from sharewarez.models import Library, GlobalSettings, AllowedFileType, ScanJob, Game
from sharewarez.platform import LibraryPlatform
from sharewarez.utilities import scan_and_add_games, handle_auto_scan, handle_manual_scan
from sqlalchemy import select


def safe_cleanup_database(db_session):
    """Completely clean up ALL test data - this is a test database, nuke everything!"""
    from sqlalchemy import text
    
    try:
        # Disable foreign key checks temporarily for aggressive cleanup
        db_session.execute(text("SET session_replication_role = replica;"))
        
        # Delete all junction table data first
        db_session.execute(text("TRUNCATE TABLE user_favorites CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_genre_association CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_platform_association CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_game_mode_association CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_theme_association CASCADE"))
        
        # Delete all main table data
        for table in ['game_updates', 'game_extras', 'images', 'game_urls', 'unmatched_folders', 
                     'scan_jobs', 'download_requests', 'newsletters', 'system_events', 
                     'invite_tokens', 'games', 'users', 'libraries']:
            try:
                db_session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            except Exception:
                pass  # Table might not exist
        
        # Re-enable foreign key checks
        db_session.execute(text("SET session_replication_role = DEFAULT;"))
        
        db_session.commit()
        
    except Exception as e:
        db_session.rollback()
        print(f"❌ Error during aggressive cleanup in test_utilities.py: {e}")
        # Try to re-enable foreign key checks
        try:
            db_session.execute(text("SET session_replication_role = DEFAULT;"))
            db_session.commit()
        except:
            pass


@pytest.fixture(autouse=True)
def cleanup_after_each_test(db_session):
    """Automatically clean up after each test - no test data should persist!"""
    yield  # Let the test run first
    safe_cleanup_database(db_session)  # Clean up after


class TestScanAndAddGamesCore:
    def test_active_scan_raises_without_creating_detail(self, app):
        from sharewarez.utils.scan_lifecycle import ScanRunError
        with app.app_context(), patch('sharewarez.utilities.is_scan_job_running', return_value=True):
            before = db.session.query(ScanJob).count()
            with pytest.raises(ScanRunError, match='already in progress'):
                scan_and_add_games('/fake/path', library_uuid=str(uuid4()))
            assert db.session.query(ScanJob).count() == before

    def test_missing_library_raises_without_creating_detail(self, app):
        from sharewarez.utils.scan_lifecycle import ScanRunError
        with app.app_context(), patch('sharewarez.utilities.is_scan_job_running', return_value=False):
            before = db.session.query(ScanJob).count()
            with pytest.raises(ScanRunError, match='Library not found'):
                scan_and_add_games('/fake/path', library_uuid=str(uuid4()))
            assert db.session.query(ScanJob).count() == before


class TestHandleAutoScanCore:
    """Test core functionality of handle_auto_scan with comprehensive assertions."""
    
    def test_form_validation_failure_with_mock_form(self, app, db_session):
        """Test comprehensive behavior when form validation fails."""
        test_uuid = str(uuid4())
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = False
        mock_form.library_uuid.data = test_uuid
        mock_form.errors = {'folder_path': ['This field is required.'], 'scan_mode': ['Invalid choice.']}
        
        with app.app_context():
            with app.test_request_context():
                # Track initial state
                initial_scan_jobs = db_session.execute(select(ScanJob)).scalars().all()
                initial_count = len(initial_scan_jobs)
                
                with patch('sharewarez.utilities.flash') as mock_flash:
                    with patch('sharewarez.utilities.redirect') as mock_redirect:
                        with patch('sharewarez.utilities.url_for') as mock_url_for:
                            mock_session = {}
                            with patch('sharewarez.utilities.session', mock_session):
                                mock_url_for.return_value = '/scan'
                                mock_redirect.return_value = 'redirected_response'
                                
                                result = handle_auto_scan(mock_form)
                                
                                # Verify flash was called with specific error details
                                mock_flash.assert_called_once()
                                flash_call = mock_flash.call_args[0][0]  # Get the message
                                assert 'validation failed' in flash_call.lower()
                                assert str(mock_form.errors) in flash_call
                                
                                # Note: session['active_tab'] is NOT set in validation failure case
                                # The session should remain empty since the function doesn't set it on validation failure
                                assert 'active_tab' not in mock_session
                                
                                # Verify redirect is called with correct parameters
                                mock_redirect.assert_called_once()
                                mock_url_for.assert_called_with(
                                    'main.admin_scan_management',
                                    library_uuid=test_uuid, 
                                    active_tab='auto'
                                )
                                
                                # Critical assertion: No scan job created on validation failure
                                final_scan_jobs = db_session.execute(select(ScanJob)).scalars().all()
                                assert len(final_scan_jobs) == initial_count, "No scan job should be created on validation failure"
                                
                                # Verify form was accessed correctly
                                mock_form.validate_on_submit.assert_called_once()
                                assert result == 'redirected_response'

    def test_scan_already_running_comprehensive_checks(self, app, db_session):
        """Test comprehensive behavior when scan is already running."""
        test_uuid = str(uuid4())
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = True
        mock_form.library_uuid.data = test_uuid
        mock_form.remove_missing.data = True
        mock_form.download_missing_images.data = False
        
        # Create library for the running scan job
        running_library = Library(
            uuid=str(uuid4()),
            name="Running Scan Library", 
            platform=LibraryPlatform.PCWIN
        )
        db_session.add(running_library)
        
        # Create actual running scan job in database
        running_job = ScanJob(
            folders={"/test/path": True},
            content_type='Games',
            status='Running',
            is_enabled=True,
            last_run=datetime.now(),
            library_uuid=running_library.uuid,  # Use valid library UUID
            error_message='',
            total_folders=5,
            folders_success=2,
            folders_failed=1,
            scan_folder='/test/path'
        )
        db_session.add(running_job)
        db_session.commit()
        
        with app.app_context():
            with app.test_request_context():
                with patch('sharewarez.utilities.flash') as mock_flash:
                    with patch('sharewarez.utilities.redirect') as mock_redirect:
                        with patch('sharewarez.utilities.url_for') as mock_url_for:
                            mock_session = {}
                            with patch('sharewarez.utilities.session', mock_session):
                                mock_url_for.return_value = '/scan_management'
                                mock_redirect.return_value = 'blocked_response'
                                
                                result = handle_auto_scan(mock_form)
                                
                                # Verify exact flash message and category
                                mock_flash.assert_called_once_with(
                                    'A scan is already in progress. Please wait until the current scan completes.', 
                                    'error'
                                )
                                
                                # Verify session state management
                                assert mock_session['active_tab'] == 'auto'
                                
                                # Verify redirect parameters
                                mock_url_for.assert_called_once_with(
                                    'main.admin_scan_management',
                                    library_uuid=test_uuid,
                                    active_tab='auto'
                                )
                                
                                # Critical assertion: Verify running job still exists unchanged
                                # Query the job again instead of refreshing to avoid session issues
                                persistent_job = db_session.get(ScanJob, running_job.id)
                                assert persistent_job is not None
                                assert persistent_job.status == 'Running'
                                assert persistent_job.folders_success == 2
                                assert persistent_job.folders_failed == 1
                                
                                # Verify no new scan job was created for our library
                                new_jobs = db_session.execute(
                                    select(ScanJob).filter_by(library_uuid=test_uuid)
                                ).scalars().all()
                                assert len(new_jobs) == 0, "No new scan job should be created when one is running"
                                
                                # Verify form data was accessed
                                mock_form.validate_on_submit.assert_called_once()
                                mock_form.remove_missing.data  # Should not raise AttributeError
                                
                                assert result == 'blocked_response'


class TestHandleManualScanCore:
    """Test core functionality of handle_manual_scan with proper mocking."""
    
    def test_form_validation_failure(self, app):
        """Test behavior when form validation fails.""" 
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = False
        mock_form.library_uuid.data = str(uuid4())
        
        with app.app_context():
            with app.test_request_context():
                mock_session = {}
                with patch('sharewarez.utilities.session', mock_session):
                    with patch('sharewarez.utilities.flash') as mock_flash:
                        with patch('sharewarez.utilities.redirect'):
                            with patch('sharewarez.utilities.url_for'):
                                handle_manual_scan(mock_form)
                                
                                mock_flash.assert_called_with('Manual scan form validation failed.', 'error')
                                assert mock_session['active_tab'] == 'manual'

    def test_scan_already_running(self, app):
        """Test behavior when scan is already running."""
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = True
        mock_form.library_uuid.data = str(uuid4())
        
        mock_running_job = Mock()
        
        with app.app_context():
            with app.test_request_context():
                with patch('sharewarez.utilities.db.session') as mock_db_session:
                    mock_session = {}
                    with patch('sharewarez.utilities.session', mock_session):
                        with patch('sharewarez.utilities.flash') as mock_flash:
                            with patch('sharewarez.utilities.redirect'):
                                with patch('sharewarez.utilities.url_for'):
                                    mock_db_session.execute.return_value.scalars.return_value.first.return_value = mock_running_job
                                    
                                    handle_manual_scan(mock_form)
                                    
                                    mock_flash.assert_called_with(
                                        'A scan is already in progress. Please wait until the current scan completes.', 
                                        'error'
                                    )
                                    assert mock_session['active_tab'] == 'manual'


class TestUtilitiesWithRealDatabase:
    def test_invalid_target_persists_failure_and_raises(self, app, db_session):
        from sharewarez.utils.scan_lifecycle import ScanRunError
        library = Library(name=f'Invalid {uuid4().hex}', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        if not db_session.query(AllowedFileType).first():
            db_session.add(AllowedFileType(value='exe'))
        db_session.commit()
        with patch('sharewarez.utilities.is_scan_job_running', return_value=False):
            with pytest.raises(ScanRunError):
                scan_and_add_games('/invalid/target', library_uuid=library.uuid)
        row = db_session.query(ScanJob).filter_by(library_uuid=library.uuid).one()
        assert row.status == 'Failed' and row.outcome == 'failed'
        assert 'No removals performed' in row.error_message

    def test_remove_missing_games_functionality(self, app, db_session, tmp_path):
        """Cleanup applies only to direct records under the selected target."""
        app.config.update(BASE_FOLDER_POSIX=str(tmp_path), DATA_FOLDER_WAREZ=str(tmp_path))
        library = Library(name=f'Cleanup {uuid4().hex}', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.flush()
        (tmp_path / 'Present').mkdir()
        present = Game(name='Present', full_disk_path=str(tmp_path / 'Present'), library_uuid=library.uuid)
        missing = Game(name='Missing', full_disk_path=str(tmp_path / 'Missing'), library_uuid=library.uuid)
        elsewhere = Game(name='Other root', full_disk_path=str(tmp_path.parent / 'offline' / 'Missing'), library_uuid=library.uuid)
        db_session.add_all([present, missing, elsewhere])
        if not db_session.query(AllowedFileType).first():
            db_session.add(AllowedFileType(value='exe'))
        db_session.commit()
        with patch('sharewarez.utilities.is_scan_job_running', return_value=False), patch('sharewarez.utilities.remove_from_lib', return_value=True) as remove:
            scan_and_add_games(str(tmp_path), library_uuid=library.uuid, remove_missing=True)
        remove.assert_called_once_with(missing.uuid)
        job = db_session.execute(select(ScanJob).filter_by(library_uuid=library.uuid)).scalar_one()
        assert job.removed_count == 1
        assert job.status == 'Completed'
