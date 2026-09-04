import pytest
import json
from flask import url_for
from unittest.mock import patch, MagicMock
from sharewarez.models import User, DownloadRequest, DownloadTransfer, Game, GameUpdate, Library
from sharewarez.platform import LibraryPlatform
from sharewarez import db
from uuid import uuid4
from datetime import datetime, timedelta, timezone


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    admin_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=admin_uuid,
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    """Create a regular user."""
    user_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=user_uuid,
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        is_email_verified=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_library(db_session):
    """Create a test library."""
    library = Library(
        name='Test Library',
        platform=LibraryPlatform.PCWIN
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture 
def test_game(db_session, test_library):
    """Create a test game."""
    game = Game(
        name='Test Game',
        library_uuid=test_library.uuid
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def sample_download_request(db_session, regular_user, test_game):
    """Create a sample download request."""
    download_request = DownloadRequest(
        user_id=regular_user.id,
        game_uuid=test_game.uuid,
        status='completed',
        zip_file_path='test_game.zip',
        request_time=datetime.now(timezone.utc)
    )
    db_session.add(download_request)
    db_session.commit()
    return download_request


@pytest.fixture
def processing_download_request(db_session, regular_user, test_game):
    """Create a download request with processing status."""
    download_request = DownloadRequest(
        user_id=regular_user.id,
        game_uuid=test_game.uuid,
        status='processing',
        request_time=datetime.now(timezone.utc)
    )
    db_session.add(download_request)
    db_session.commit()
    return download_request


class TestManageDownloadsRoute:
    """Test the manage downloads admin route."""

    def test_manage_downloads_requires_admin_login(self, client, regular_user):
        """Test that manage downloads requires admin login."""
        with client.session_transaction() as session:
            session['_user_id'] = str(regular_user.id)
        
        response = client.get('/admin/manage-downloads')
        assert response.status_code == 302  # Should redirect due to lack of admin access

    def test_manage_downloads_admin_access(self, client, admin_user):
        """Test that admin can access manage downloads page."""
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/manage-downloads')
        assert response.status_code == 200
        assert b'admin_manage_downloads' in response.data or b'manage' in response.data

    def test_manage_downloads_displays_data(self, client, admin_user, sample_download_request):
        """Test that manage downloads displays download requests."""
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/manage-downloads')
        assert response.status_code == 200
        assert b'Test Game' in response.data
        assert f'/game_details/{sample_download_request.game_uuid}'.encode() in response.data

    def test_manage_downloads_displays_update_and_base_game_link(self, client, admin_user, db_session, regular_user, test_game):
        update = GameUpdate(game_uuid=test_game.uuid, file_path='/games/Test Game/updates/update-1.1.zip', title='Update 1.1')
        db_session.add(update)
        db_session.flush()
        download_request = DownloadRequest(
            user_id=regular_user.id,
            game_uuid=test_game.uuid,
            status='available',
            content_type='update',
            content_title=update.title,
            game_update_id=update.id,
            file_location=update.file_path,
        )
        db_session.add(download_request)
        db_session.commit()

        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/manage-downloads?content_type=update')

        assert response.status_code == 200
        assert b'Update 1.1' in response.data
        assert b'Update' in response.data
        assert b'Test Game' in response.data
        assert f'/game_details/{test_game.uuid}'.encode() in response.data

    def test_manage_downloads_displays_completed_and_interrupted_transfer_activity(
        self, client, admin_user, db_session, regular_user, sample_download_request
    ):
        completed = DownloadTransfer(
            user_id=regular_user.id,
            download_request_id=sample_download_request.id,
            filename='test-game.zip',
            reserved_bytes=2048,
            bytes_sent=2048,
            status='completed',
            ended_at=datetime.now(timezone.utc),
        )
        interrupted = DownloadTransfer(
            user_id=regular_user.id,
            download_request_id=sample_download_request.id,
            filename='partial-test-game.zip',
            reserved_bytes=512,
            bytes_sent=512,
            status='interrupted',
            ended_at=datetime.now(timezone.utc),
        )
        db_session.add_all([completed, interrupted])
        db_session.commit()
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/manage-downloads')

        assert response.status_code == 200
        assert b'Transfer attempts' in response.data
        assert b'test-game.zip' in response.data
        assert b'partial-test-game.zip' in response.data
        assert b'Completed' in response.data
        assert b'Interrupted' in response.data

    def test_active_transfer_feed_is_fresh_and_uses_readable_elapsed_time(
        self, client, admin_user, db_session, regular_user, sample_download_request
    ):
        transfer = DownloadTransfer(
            user_id=regular_user.id,
            download_request_id=sample_download_request.id,
            filename='large-game.zip',
            reserved_bytes=4096,
            bytes_sent=1024,
            status='active',
            started_at=datetime.now(timezone.utc) - timedelta(seconds=1036),
            last_activity_at=datetime.now(timezone.utc),
        )
        db_session.add(transfer)
        db_session.commit()
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/active-transfers')

        assert response.status_code == 200
        assert response.cache_control.no_store is True
        payload = response.get_json()['transfers']
        item = next(entry for entry in payload if entry['id'] == transfer.id)
        assert item['filename'] == 'large-game.zip'
        assert item['elapsed_label'] in {'17m 16s', '17m 17s'}
        assert 1036 <= item['elapsed_seconds'] <= 1037

    def test_active_transfer_monitor_uses_non_overlapping_live_refresh(self, client, admin_user):
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/manage-downloads')

        assert response.status_code == 200
        assert b'download_live.js' in response.data
        assert b'admin_transfer_live.js' in response.data
        assert b'id="activeTransferConnection"' in response.data
        assert b'list.replaceChildren()' not in response.data
        assert b'${transfer.elapsed_seconds}s' not in response.data

    def test_transfer_keeps_game_attribution_after_request_is_deleted(
        self, client, admin_user, db_session, regular_user, sample_download_request, test_game
    ):
        transfer = DownloadTransfer(
            user_id=regular_user.id,
            download_request_id=sample_download_request.id,
            game_uuid=test_game.uuid,
            filename='durable-game.zip',
            reserved_bytes=1024,
            bytes_sent=1024,
            status='completed',
            ended_at=datetime.now(timezone.utc),
        )
        db_session.add(transfer)
        db_session.commit()
        db_session.delete(sample_download_request)
        db_session.commit()

        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/manage-downloads')

        assert response.status_code == 200
        assert b'durable-game.zip' in response.data
        assert b'Test Game' in response.data

    @patch('sharewarez.routes_downloads_ext.admin.log_system_event')
    def test_admin_can_cancel_an_active_transfer(
        self, mock_log, client, admin_user, db_session, regular_user, sample_download_request
    ):
        transfer = DownloadTransfer(
            user_id=regular_user.id,
            download_request_id=sample_download_request.id,
            game_uuid=sample_download_request.game_uuid,
            filename='active-game.zip',
            reserved_bytes=4096,
            bytes_sent=1024,
            status='active',
        )
        db_session.add(transfer)
        db_session.commit()
        transfer_id = transfer.id
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.post(f'/admin/download-transfers/{transfer_id}/cancel')

        assert response.status_code == 302
        db_session.refresh(transfer)
        assert transfer.status == 'cancelled'
        assert transfer.reserved_bytes == 1024
        assert transfer.ended_at is not None
        mock_log.assert_called_once()

    @patch('sharewarez.routes_downloads_ext.admin.log_system_event')
    def test_clear_transfer_history_preserves_active_transfers(
        self, mock_log, client, admin_user, db_session, regular_user
    ):
        active = DownloadTransfer(
            user_id=regular_user.id, filename='active.zip', status='active'
        )
        completed = DownloadTransfer(
            user_id=regular_user.id, filename='completed.zip', status='completed',
            ended_at=datetime.now(timezone.utc),
        )
        interrupted = DownloadTransfer(
            user_id=regular_user.id, filename='interrupted.zip', status='interrupted',
            ended_at=datetime.now(timezone.utc),
        )
        db_session.add_all([active, completed, interrupted])
        db_session.commit()
        active_id = active.id
        completed_id = completed.id
        interrupted_id = interrupted.id
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.post('/admin/download-transfers/clear')

        assert response.status_code == 302
        assert db_session.get(DownloadTransfer, active_id) is not None
        assert db_session.get(DownloadTransfer, completed_id) is None
        assert db_session.get(DownloadTransfer, interrupted_id) is None
        mock_log.assert_called_once()

    def test_manage_downloads_unauthenticated(self, client):
        """Test that unauthenticated users are redirected."""
        response = client.get('/admin/manage-downloads')
        assert response.status_code == 302  # Should redirect to login


class TestDeleteDownloadRequestRoute:
    """Test the delete download request route."""

    def test_delete_requires_admin_login(self, client, regular_user, sample_download_request):
        """Test that delete requires admin login."""
        with client.session_transaction() as session:
            session['_user_id'] = str(regular_user.id)
        
        response = client.post(f'/delete_download_request/{sample_download_request.id}')
        assert response.status_code == 302  # Should redirect due to lack of admin access

    @patch('sharewarez.routes_downloads_ext.admin.log_system_event')
    def test_delete_download_request_success(self, mock_log, client, admin_user, sample_download_request, app):
        """Test successful deletion of download request."""
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.post(f'/delete_download_request/{sample_download_request.id}')
        assert response.status_code == 302  # Should redirect

        # Verify the download request was deleted from database
        deleted_request = db.session.get(DownloadRequest, sample_download_request.id)
        assert deleted_request is None

        # Verify logging was called
        mock_log.assert_called()


    def test_delete_nonexistent_download_request(self, client, admin_user):
        """Test deletion of non-existent download request."""
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        
        response = client.post('/delete_download_request/99999')
        assert response.status_code == 302  # Should redirect

    def test_delete_download_request_no_zip_file(self, client, admin_user, db_session, regular_user, test_game):
        """Test deletion of download request with no file path."""
        # Create download request without zip_file_path
        download_request = DownloadRequest(
            user_id=regular_user.id,
            game_uuid=test_game.uuid,
            status='completed',
            zip_file_path=None,  # No ZIP file
            request_time=datetime.now(timezone.utc)
        )
        db_session.add(download_request)
        db_session.commit()
        
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/delete_download_request/{download_request.id}')
        assert response.status_code == 302
        
        # Verify the download request was deleted
        deleted_request = db.session.get(DownloadRequest, download_request.id)
        assert deleted_request is None

    def test_delete_unauthenticated(self, client, sample_download_request):
        """Test that unauthenticated users cannot delete download requests."""
        response = client.post(f'/delete_download_request/{sample_download_request.id}')
        assert response.status_code == 302  # Should redirect to login


class TestDownloadPriorityRoute:
    def test_admin_can_update_download_priority(self, client, admin_user, sample_download_request):
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.post(
            f'/admin/download-priority/{sample_download_request.id}',
            json={'priority': 10},
        )

        assert response.status_code == 200
        db.session.refresh(sample_download_request)
        assert sample_download_request.priority == 10

    def test_download_priority_rejects_invalid_value(self, client, admin_user, sample_download_request):
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.post(
            f'/admin/download-priority/{sample_download_request.id}',
            json={'priority': 4},
        )

        assert response.status_code == 400


class TestDownloadCacheAdminRoute:
    def test_download_cache_requires_admin(self, client, regular_user):
        with client.session_transaction() as session:
            session['_user_id'] = str(regular_user.id)

        response = client.get('/admin/download-cache')

        assert response.status_code in {302, 403}

    def test_download_cache_admin_page(self, client, admin_user, app, tmp_path):
        app.config['DOWNLOAD_CACHE_DIR'] = str(tmp_path / 'download-cache')
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)

        response = client.get('/admin/download-cache')

        assert response.status_code == 200
        assert b'Download cache' in response.data
        assert b'Cache policy' in response.data
        assert b'Archive inventory' in response.data
        assert b'What users should expect' not in response.data


class TestIntegration:
    """Integration tests for admin download management."""

    @patch.object(DownloadRequest, 'error_message', create=True) 
    def test_full_workflow_admin_management(self, mock_error_message, client, admin_user, db_session, regular_user, test_game):
        """Test the full workflow of admin download management."""
        # Create multiple download requests with different statuses
        completed_request = DownloadRequest(
            user_id=regular_user.id,
            game_uuid=test_game.uuid,
            status='completed',
            zip_file_path='completed_game.zip',
            request_time=datetime.now(timezone.utc)
        )
        processing_request = DownloadRequest(
            user_id=regular_user.id,
            game_uuid=test_game.uuid,
            status='processing',
            request_time=datetime.now(timezone.utc)
        )
        db_session.add_all([completed_request, processing_request])
        db_session.commit()
        
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        
        # 1. View manage downloads page
        response = client.get('/admin/manage-downloads')
        assert response.status_code == 200

        # 2. Delete completed request
        with patch('sharewarez.routes_downloads_ext.admin.log_system_event'):
            response = client.post(f'/delete_download_request/{completed_request.id}')
            assert response.status_code == 302

            # Verify request was deleted
            deleted_request = db.session.get(DownloadRequest, completed_request.id)
            assert deleted_request is None

