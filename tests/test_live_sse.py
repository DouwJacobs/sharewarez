import asyncio
from datetime import datetime, timedelta, timezone
import threading
from uuid import uuid4

from flask import Flask
import pytest

from sharewarez.live_snapshots import LiveAccessDenied, snapshot
from sharewarez.live_sse import DownloadEventStream
from sharewarez.models import DownloadTransfer, User


def scope(**changes):
    result = {"type": "http", "method": "GET", "scheme": "http", "headers": [(b"host", b"localhost")],
              "query_string": b"view=activity"}
    result.update(changes)
    return result


def stream(snapshotter, **kwargs):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://unused/test"
    service = DownloadEventStream(app, snapshotter=snapshotter, interval=0.001, heartbeat=0.01, **kwargs)
    service.listener.start = lambda: None
    return service


@pytest.mark.parametrize("request_scope,status", [
    (scope(method="POST"), 405),
    (scope(headers=[(b"host", b"localhost"), (b"origin", b"https://evil.example")]), 403),
    (scope(query_string=b"view=unknown"), 400),
    (scope(query_string=b"ids=invalid"), 400),
])
def test_rejects_invalid_boundary_before_database(request_scope, status):
    async def run():
        messages = []
        async def send(message):
            messages.append(message)
        def never(*args):
            pytest.fail("Boundary rejection should not query the database")
        await stream(never)(request_scope, None, send)
        assert messages[0]["status"] == status
    asyncio.run(run())


def test_initial_heartbeat_reauthorization_and_disconnect_cleanup():
    async def run():
        main_thread = threading.get_ident()
        calls, messages = [], []
        def read(*args):
            assert threading.get_ident() != main_thread
            calls.append(1)
            if len(calls) == 3:
                raise LiveAccessDenied(403)
            return {"user_id": 1, "transfers": [], "sequence": len(calls)}
        async def receive():
            await asyncio.Future()
        async def send(message):
            messages.append(message)
        service = stream(read)
        await asyncio.wait_for(service(scope(), receive, send), 1)
        bodies = [message.get("body", b"") for message in messages]
        assert sum(b"event: snapshot" in body for body in bodies) == 2
        assert b"event: access-revoked" in bodies[-1]
        assert not service.hub._subscriptions
    asyncio.run(run())


def test_slow_client_times_out_and_releases_connection():
    async def run():
        service = stream(lambda *args: {"user_id": 1}, send_timeout=0.01)
        async def send(message):
            await asyncio.Future()
        async def receive():
            await asyncio.Future()
        await asyncio.wait_for(service(scope(), receive, send), 1)
        assert not service.hub._subscriptions
    asyncio.run(run())


def test_sse_central_security_headers_and_correlation():
    async def run():
        messages = []
        async def send(message):
            messages.append(message)
        service = stream(lambda *args: {'user_id':1})
        await service(scope(method='POST', scheme='https', headers=[(b'x-request-id',b'live-test-123')]), None, send)
        headers = dict(messages[0]['headers'])
        assert headers[b'x-request-id'] == b'live-test-123'
        assert b'server-timing' in headers
        assert headers[b'x-content-type-options'] == b'nosniff'
        assert b'content-security-policy' in headers and b'strict-transport-security' in headers
    asyncio.run(run())


def test_close_wakes_idle_stream_and_completes_response():
    async def run():
        service = stream(lambda *args: {'user_id':1})
        service.heartbeat = 100
        started = asyncio.Event()
        messages = []
        async def send(message):
            messages.append(message)
            if message['type'] == 'http.response.body': started.set()
        async def receive():
            await asyncio.Future()
        task = asyncio.create_task(service(scope(), receive, send))
        await asyncio.wait_for(started.wait(),1)
        await service.close()
        await asyncio.wait_for(task,1)
        assert messages[-1].get('more_body') is False
        assert not service.hub._subscriptions
    asyncio.run(run())


def test_asgi_lifespan_does_not_replace_server_signal_handlers(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from asgi import LazyASGIApp
    import signal
    monkeypatch.setattr('sharewarez.utils.shutdown.request_shutdown', Mock())
    async def run():
        before = signal.getsignal(signal.SIGINT)
        app = LazyASGIApp()
        app._download_events = Mock(close=AsyncMock())
        messages = iter([{'type':'lifespan.startup'},{'type':'lifespan.shutdown'}])
        async def receive(): return next(messages)
        send = AsyncMock()
        await app({'type':'lifespan'}, receive, send)
        assert [call.args[0]['type'] for call in send.call_args_list] == ['lifespan.startup.complete','lifespan.shutdown.complete']
        app._download_events.close.assert_awaited_once()
        assert signal.getsignal(signal.SIGINT) is before
    asyncio.run(run())


def test_disconnect_during_idle_does_not_wait_for_heartbeat():
    async def run():
        service = stream(lambda *args: {"user_id": 1})
        service.heartbeat = 100
        queue = asyncio.Queue()
        async def send(message):
            if message["type"] == "http.response.body":
                await queue.put({"type": "http.disconnect"})
        await asyncio.wait_for(service(scope(), queue.get, send), 1)
        assert not service.hub._subscriptions
    asyncio.run(run())


def test_snapshot_owner_admin_and_account_revocation(app, db_session):
    suffix = uuid4().hex
    users = [User(name=f"live-{index}-{suffix}", email=f"live-{index}-{suffix}@example.test",
                  role="admin" if index == 2 else "user", state=True, password_hash="test") for index in range(3)]
    db_session.add_all(users)
    db_session.flush()
    now = datetime.now(timezone.utc)
    transfers = [DownloadTransfer(user_id=user.id, filename=f"private-{index}", bytes_sent=1000,
                                 reserved_bytes=2000, started_at=now-timedelta(seconds=10))
                 for index, user in enumerate(users[:2])]
    db_session.add_all(transfers)
    db_session.commit()
    def signed(user):
        token = app.session_interface.get_signing_serializer(app).dumps({"_user_id": str(user.id)})
        return scope(headers=[(b"cookie", f"session={token}".encode())])
    result = snapshot(app, signed(users[0]), "downloads", ())
    assert [item["id"] for item in result["transfers"]] == [transfers[0].id]
    assert "filename" not in result["transfers"][0]
    assert 95 <= result["transfers"][0]["average_speed"] <= 100
    with pytest.raises(LiveAccessDenied):
        snapshot(app, signed(users[0]), "activity", ())
    result = snapshot(app, signed(users[2]), "activity", ())
    assert {item.id for item in transfers} <= {item["id"] for item in result["transfers"]}
    users[0].state = False
    db_session.commit()
    with pytest.raises(LiveAccessDenied):
        snapshot(app, signed(users[0]), "downloads", ())
    with pytest.raises(LiveAccessDenied):
        snapshot(app, scope(), "downloads", ())


def test_download_payload_preparing_ready_and_fallback_policy():
    from types import SimpleNamespace
    from sharewarez.live_snapshots import download_payload
    policy = {"archiveCacheMode": "prefer", "archiveCacheFallbackEnabled": True}
    archive = SimpleNamespace(state="building", bytes_written=99, source_bytes=100, failure_message=None)
    item = SimpleNamespace(id=1, status="processing", delivery_kind="cached_archive",
                           download_size=100, expires_at=None, archive=archive)
    preparing = download_payload(item, policy)
    assert preparing["archive"]["progress"] == 99
    assert preparing["fallback_available"] and not preparing["available"]
    archive.state = "ready"
    item.status = "available"
    ready = download_payload(item, policy)
    assert ready["available"] and ready["archive"]["state"] == "ready"
    assert ready["archive"]["progress"] is None
    policy["archiveCacheFallbackEnabled"] = False
    assert not download_payload(item, policy)["fallback_available"]


def test_cache_snapshot_stage_leases_and_admin_only_polling(app, db_session, client, tmp_path):
    from sharewarez.models import DownloadArchive, BackgroundJob
    from sharewarez.live_snapshots import cache_payload
    app.config['DOWNLOAD_CACHE_DIR'] = str(tmp_path / 'cache')
    suffix = uuid4().hex
    user = User(name=f'cache-live-{suffix}', email=f'{suffix}@example.test', role='admin',
                state=True, password_hash='test')
    job = BackgroundJob(task_name='download.archive.build', queue='archive', status='running',
                        progress=97, progress_message='Flushing archive', cancel_requested=True)
    db_session.add_all([user, job]); db_session.flush()
    archive = DownloadArchive(id=str(uuid4()), cache_key=uuid4().hex * 2, source_path='/not-exposed',
                              display_name='Test archive', state='building', source_bytes=100,
                              bytes_written=99, build_job_id=job.id)
    db_session.add(archive); db_session.flush()
    transfer = DownloadTransfer(user_id=user.id, archive_id=archive.id, filename='test.zip')
    db_session.add(transfer); db_session.commit()
    import json
    cache_data = cache_payload([archive.id])
    json.dumps(cache_data)  # ASGI SSE uses the standard encoder, not Flask's Decimal conversion.
    result = cache_data['archives'][0]
    assert result['progress'] == 97 and result['progress_message'] == 'Flushing archive'
    assert result['active_leases'] == 1 and result['cancel_requested']
    assert 'source_path' not in result
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    response = client.get('/admin/download-cache/status?ids=' + archive.id)
    assert response.status_code == 200 and response.cache_control.no_store
    assert response.json['archives'][0]['id'] == archive.id
    user.role = 'user'; db_session.commit()
    denied = client.get('/admin/download-cache/status?ids=' + archive.id)
    assert denied.status_code == 302 and denied.json is None


def test_shared_snapshot_cache_never_caches_authorization(app, db_session):
    from sharewarez.live_snapshot_cache import SnapshotCache
    suffix = uuid4().hex
    user = User(name=f'cached-admin-{suffix}', email=f'{suffix}@example.test', role='admin',
                state=True, password_hash='test')
    db_session.add(user); db_session.commit()
    user_id = user.id
    token = app.session_interface.get_signing_serializer(app).dumps({'_user_id': str(user_id)})
    request_scope = scope(headers=[(b'cookie', f'session={token}'.encode())])
    cache = SnapshotCache(ttl=60)
    snapshot(app, request_scope, 'activity', (), cache=cache)
    db_session.get(User, user_id).role = 'user'
    db_session.commit()
    with pytest.raises(LiveAccessDenied):
        snapshot(app, request_scope, 'activity', (), cache=cache)
