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

        response = client.get('/admin/manage-downloads?view=links')
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

        from bs4 import BeautifulSoup
        page = BeautifulSoup(client.get('/admin/manage-downloads?view=activity&user=' + regular_user.name).data, 'html.parser')
        form = page.select_one('form[action="/admin/download-transfers/clear"]')
        data = {node['name']: node.get('value', '') for node in form.select('input[name]')}
        response = client.post('/admin/download-transfers/clear', data=data)
        assert response.status_code == 302
        db_session.expire_all()
        assert db_session.get(DownloadTransfer, active_id).admin_history_hidden_at is None
        assert db_session.get(DownloadTransfer, completed_id).admin_history_hidden_at is not None
        assert db_session.get(DownloadTransfer, interrupted_id).admin_history_hidden_at is not None
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


class TestDeliveryViews:
    def test_one_link_two_attempts_have_separate_views(self, client, admin_user, db_session, regular_user, sample_download_request):
        from bs4 import BeautifulSoup
        attempts = [DownloadTransfer(user_id=regular_user.id, download_request_id=sample_download_request.id,
                    filename='journey.zip', status=state) for state in ('interrupted', 'completed')]
        db_session.add_all(attempts)
        db_session.commit()
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        activity = BeautifulSoup(client.get(f'/admin/manage-downloads?request_id={sample_download_request.id}').data, 'html.parser')
        assert len(activity.select('tr[data-transfer-id]')) == 2
        assert not activity.select('tr[data-download-id]')
        links = BeautifulSoup(client.get(f'/admin/manage-downloads?view=links&user={regular_user.name}').data, 'html.parser')
        assert len(links.select('tr[data-download-id]')) == 1
        assert not links.select('tr[data-transfer-id]')
        assert f'view=activity&request_id={sample_download_request.id}' in str(links).replace('&amp;', '&')

    def test_history_hiding_requires_reviewed_filters(self, client, admin_user, db_session, regular_user):
        attempt = DownloadTransfer(user_id=regular_user.id, filename='retained.zip', status='completed', bytes_sent=123, reserved_bytes=123)
        db_session.add(attempt)
        db_session.commit()
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        response = client.post('/admin/download-transfers/clear')
        assert response.status_code == 400
        assert db_session.get(DownloadTransfer, attempt.id) is not None

    @pytest.mark.parametrize('query,view', [
        ('', 'activity'), ('status=failed', 'links'), ('page=2', 'links'),
        ('content_type=extra', 'links'), ('status=failed&transfer_status=', 'activity'),
        ('page=2&transfer_page=1', 'activity'), ('view=links&transfer_status=active', 'links'),
        ('view=activity&status=failed', 'activity'),
    ])
    def test_legacy_view_precedence(self, client, admin_user, query, view):
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        page = client.get('/admin/manage-downloads?' + query)
        assert page.status_code == 200
        assert f'id="deliveryResults" data-view="{view}"'.encode() in page.data

    @pytest.mark.parametrize('query', ['view=nope', 'view=activity&request_id=-1', 'view=activity&request_id=abc',
        'view=activity&transfer_status=bogus', 'view=links&content_type=bogus', 'per_page=101',
        'transfer_page=0', 'view=links&status=active', 'user=a&user=b'])
    def test_bad_filters_rejected_on_page_and_poll(self, client, admin_user, query):
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        for path in ('/admin/manage-downloads?', '/admin/download-delivery/status?'):
            assert client.get(path + query).status_code == 400

    def test_hide_filtered_evidence_preserves_real_quota_and_member_recovery(self, app, client, admin_user, db_session, regular_user, sample_download_request):
        from bs4 import BeautifulSoup
        from sharewarez.utils.download_limits import reserve_transfer
        from sharewarez.utils.download_state import transfer_context
        other = User(name='Other-' + uuid4().hex, email=uuid4().hex + '@test.example', password_hash='unused', role='user')
        db_session.add(other)
        db_session.flush()
        regular_user.monthly_download_quota_bytes = 200
        finished = DownloadTransfer(user_id=regular_user.id, download_request_id=sample_download_request.id,
            filename='retained.zip', status='interrupted', bytes_sent=123, reserved_bytes=123, end_reason='peer_disconnect')
        active = DownloadTransfer(user_id=regular_user.id, filename='active.zip', status='active', reserved_bytes=10)
        unrelated = DownloadTransfer(user_id=other.id, filename='other.zip', status='completed', reserved_bytes=77, bytes_sent=77)
        db_session.add_all([finished, active, unrelated]); db_session.commit()
        ids = finished.id, active.id, unrelated.id
        owner_id, link_id = regular_user.id, sample_download_request.id
        before = reserve_transfer(owner_id, 'over-quota.bin', 100)
        assert before == (None, 133, 200)
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        url = '/admin/manage-downloads?view=activity&user=' + regular_user.name + '&request_id=' + str(link_id)
        soup = BeautifulSoup(client.get(url).data, 'html.parser')
        form = soup.select_one('form[action="/admin/download-transfers/clear"]')
        data = {node['name']: node.get('value', '') for node in form.select('input[name]')}
        assert '1 finished attempt matches these filters' in form.get_text(' ', strip=True)
        for altered in ({**data, 'user': ''}, {key: value for key, value in data.items() if key != 'request_id'}, {**data, 'review_token': 'tampered'}):
            assert client.post('/admin/download-transfers/clear', data=altered).status_code == 400
        response = client.post('/admin/download-transfers/clear', data=data)
        assert response.status_code == 302
        db_session.expire_all()
        rows = [db_session.get(DownloadTransfer, id_) for id_ in ids]
        assert rows[0].admin_history_hidden_at is not None
        assert all(row.admin_history_hidden_at is None for row in rows[1:])
        assert rows[0].bytes_sent == rows[0].reserved_bytes == 123
        assert rows[0].end_reason == 'peer_disconnect'
        active_map, latest_map = transfer_context([db_session.get(DownloadRequest, link_id)])
        assert latest_map[link_id].id == ids[0]
        after = reserve_transfer(owner_id, 'over-quota.bin', 100)
        assert after == before
        assert b'retained.zip' not in client.get(url).data
        assert client.post('/admin/download-transfers/clear', data=data).status_code == 409

    def test_hide_rejects_changed_preview_count(self, client, admin_user, db_session, regular_user):
        from bs4 import BeautifulSoup
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        url = '/admin/manage-downloads?view=activity&user=' + regular_user.name
        form = BeautifulSoup(client.get(url).data, 'html.parser').select_one('form[action="/admin/download-transfers/clear"]')
        data = {node['name']: node.get('value', '') for node in form.select('input[name]')}
        finished = DownloadTransfer(user_id=regular_user.id, filename='new.zip', status='completed')
        db_session.add(finished); db_session.commit()
        assert client.post('/admin/download-transfers/clear', data=data).status_code == 409
        db_session.refresh(finished)
        assert finished.admin_history_hidden_at is None

    def test_scoped_pages_match_live_and_poll_and_terminal_transition(self, app, client, admin_user, db_session, regular_user, sample_download_request):
        from bs4 import BeautifulSoup
        from urllib.parse import urlencode
        from sharewarez.live_snapshots import snapshot
        from sharewarez.live_snapshot_cache import SnapshotCache
        from sharewarez.live_events import LiveEventHub
        attempts = [DownloadTransfer(user_id=regular_user.id, download_request_id=sample_download_request.id,
                    filename=f'page-{index}.bin', status='active' if index == 11 else 'completed') for index in range(12)]
        db_session.add_all(attempts); db_session.commit()
        ids = sorted([item.id for item in attempts], reverse=True)
        token = app.session_interface.get_signing_serializer(app).dumps({'_user_id': str(admin_user.id)})
        cache = SnapshotCache(ttl=60)
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        base = dict(view='activity', user=regular_user.name, per_page='10')
        def read(params):
            query = urlencode(params)
            scope = dict(scheme='http', headers=[(b'cookie', f'session={token}'.encode())], query_string=query.encode())
            data = snapshot(app, scope, 'activity', (), cache=cache)
            page = BeautifulSoup(client.get('/admin/manage-downloads?' + query).data, 'html.parser')
            poll = client.get('/admin/download-delivery/status?' + query)
            assert poll.cache_control.no_store
            polled = BeautifulSoup(poll.json['html'], 'html.parser')
            assert [int(row['data-transfer-id']) for row in page.select('tr[data-transfer-id]')] == [row['id'] for row in data['transfers']]
            assert [row['data-transfer-id'] for row in polled.select('tr[data-transfer-id]')] == [row['data-transfer-id'] for row in page.select('tr[data-transfer-id]')]
            return data, page
        first, page = read(base)
        assert [row['id'] for row in first['transfers']] == ids[:10]
        second, _ = read({**base, 'transfer_page': '2'})
        assert [row['id'] for row in second['transfers']] == ids[10:]
        unmatched, _ = read({**base, 'user': 'no-such-member-' + uuid4().hex})
        assert unmatched['total'] == 0 and unmatched['transfers'] == []
        # A separate filtered browser cannot inherit the cached first page.
        filtered, _ = read({**base, 'transfer_status': 'active'})
        assert [row['id'] for row in filtered['transfers']] == [ids[0]]
        newest = db_session.get(DownloadTransfer, ids[0])
        newest.status = 'interrupted'; newest.end_reason = 'peer_disconnect'; newest.ended_at = datetime.now(timezone.utc)
        db_session.commit()
        LiveEventHub().signal({'transfers'})  # The same notification path used across web processes.
        terminal, page = read(base)
        assert terminal['transfers'][0]['end_reason'] == 'peer_disconnect'
        assert b'Connection closed' in str(page).encode() or terminal['transfers'][0]['end_reason_label'] in page.get_text()
        active_only, _ = read({**base, 'transfer_status': 'active'})
        assert active_only['transfers'] == []
        for anchor in page.select('nav[aria-label="Download delivery views"] a'):
            assert 'per_page=10' in anchor['href'] and 'transfer_page=' not in anchor['href']
        pager = page.select_one('nav[aria-label="Transfer history pagination"] a')
        assert 'view=activity' in pager['href'] and 'transfer_page=2' in pager['href']
        assert 'content_type=' not in pager['href'] and '&page=' not in pager['href']

    def test_literal_username_and_admin_only_poll(self, client, admin_user, regular_user):
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        assert client.get('/admin/download-delivery/status?user=%25').json['total'] == 0

    def test_poll_requires_admin(self, client, regular_user):
        with client.session_transaction() as session:
            session['_user_id'] = str(regular_user.id)
        assert client.get('/admin/download-delivery/status').status_code in (302, 403)

    def test_links_pager_preserves_only_its_filters(self, client, admin_user, db_session, regular_user, test_game):
        from bs4 import BeautifulSoup
        db_session.add_all([DownloadRequest(user_id=regular_user.id, game_uuid=test_game.uuid, status='available', content_type='extra', content_title=f'Extra {index}') for index in range(12)])
        db_session.commit()
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_user.id)
        query = f'view=links&user={regular_user.name}&status=available&content_type=extra&per_page=10&transfer_status=active'
        page = BeautifulSoup(client.get('/admin/manage-downloads?' + query).data, 'html.parser')
        assert len(page.select('tr[data-download-id]')) == 10
        href = page.select_one('nav[aria-label="Download links pagination"] a')['href']
        assert 'page=2' in href and 'status=available' in href and 'content_type=extra' in href and 'per_page=10' in href
        assert 'transfer_status' not in href and 'transfer_page' not in href
        second = BeautifulSoup(client.get(href).data, 'html.parser')
        assert len(second.select('tr[data-download-id]')) == 2
        poll = client.get('/admin/download-delivery/status?' + query)
        assert poll.status_code == 200 and poll.json['total'] == 12

    @pytest.mark.parametrize('api', [False, True])
    def test_admin_delete_observes_transfer_committed_while_waiting_for_owner(self, app, admin_user, db_session, regular_user, sample_download_request, monkeypatch, api):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from sqlalchemy import select
        from sharewarez.utils.download_state import lock_download
        from sharewarez.routes_downloads_ext import admin as admin_routes
        from sharewarez.routes_apis import download as api_routes
        uid, link_id, admin_id = regular_user.id, sample_download_request.id, admin_user.id
        db_session.commit()
        locked, posting, release = Event(), Event(), Event()
        def lock(*args, **kwargs):
            posting.set()
            return lock_download(*args, **kwargs)
        monkeypatch.setattr(api_routes if api else admin_routes, 'lock_download', lock)
        def writer():
            with app.app_context():
                db.session.execute(select(User).where(User.id == uid).with_for_update()).scalar_one()
                db.session.add(DownloadTransfer(user_id=uid, download_request_id=link_id, filename='admitted.zip', status='active'))
                db.session.flush(); locked.set()
                assert release.wait(5)
                db.session.commit()
        def delete_link():
            with app.app_context(), app.test_client() as browser:
                with browser.session_transaction() as session:
                    session['_user_id'] = str(admin_id)
                return (browser.delete(f'/api/delete_download/{link_id}') if api else browser.post(f'/delete_download_request/{link_id}')).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            inserting = executor.submit(writer)
            assert locked.wait(5)
            deleting = executor.submit(delete_link)
            try:
                assert posting.wait(5)
            finally:
                release.set()
            inserting.result(timeout=5)
            assert deleting.result(timeout=5) == (409 if api else 302)
        db_session.expire_all()
        assert db_session.get(DownloadRequest, link_id) is not None
        attempt = db_session.scalar(select(DownloadTransfer).where(DownloadTransfer.download_request_id == link_id))
        assert attempt is not None and attempt.status == 'active'
