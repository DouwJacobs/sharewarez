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
