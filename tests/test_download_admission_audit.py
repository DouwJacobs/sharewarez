"""Real PostgreSQL admission and real archive-byte streaming regressions."""

import asyncio
import threading
import time
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import create_engine, text, select
from sharewarez import db
from sharewarez.models import User, DownloadQueueEntry, DownloadTransfer
from sharewarez.utils.download_limits import acquire_download_slot, acquire_queued_download_slot, download_lock_engine
from sharewarez.utils.download_cache import request_resumable_archive, build_archive
from tests.test_download_cache import _cache_download_fixture
from asgi import LazyASGIApp


def test_full_general_pool_does_not_block_admission_or_loop(app, db_session):
    user = User(name=uuid4().hex, email=uuid4().hex + "@example.test", role="user", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    engine = create_engine(db.engine.url, pool_size=1, max_overflow=0, pool_timeout=0.3)
    held = engine.connect()

    async def exercise():
        started = time.monotonic()
        task = asyncio.create_task(acquire_queued_download_slot(engine, user.id, 1, wait_seconds=0))
        await asyncio.sleep(0.01)
        lag = time.monotonic() - started
        slot = await task
        assert lag < 0.1
        assert slot is not None
        assert engine.pool.checkedout() == 1
        await asyncio.to_thread(slot.release)
        return lag

    try:
        lag = asyncio.run(exercise())
        print("POOL_PRESSURE_TIMER_MS", lag * 1000)
    finally:
        held.close()
        download_lock_engine(engine).dispose()
        engine.dispose()


def test_cancelled_admission_removes_queue_and_releases_late_slot(app, db_session, monkeypatch):
    user = User(name=uuid4().hex, email=uuid4().hex + "@example.test", role="user", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    engine = db.engine
    held = acquire_download_slot(engine, user.id, 1)

    async def cancel_queued():
        task = asyncio.create_task(acquire_queued_download_slot(engine, user.id, 1, wait_seconds=5))
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(cancel_queued())
        assert db_session.scalar(select(DownloadQueueEntry.id).where(DownloadQueueEntry.user_id == user.id)) is None
    finally:
        held.release()
    entered = threading.Event()

    def slow_acquire(*args):
        entered.set()
        time.sleep(0.1)
        return acquire_download_slot(*args)

    monkeypatch.setattr("sharewarez.utils.download_limits.acquire_download_slot", slow_acquire)

    async def cancel_acquiring():
        task = asyncio.create_task(acquire_queued_download_slot(engine, user.id, 1, wait_seconds=0))
        while not entered.is_set():
            await asyncio.sleep(0.005)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancel_acquiring())
    assert download_lock_engine(engine).pool.checkedout() == 0
    assert (
        db_session.scalar(
            text("SELECT count(*) FROM pg_locks WHERE locktype = :kind AND classid = :user_id"),
            {"kind": "advisory", "user_id": user.id},
        )
        == 0
    )


def test_built_archive_resume_and_interruption_record_real_bytes(app, db_session, tmp_path):
    source, user, game, request = _cache_download_fixture(db_session, app, tmp_path, suffix="asgi")
    (source / "large.bin").write_bytes(b"x" * 4_000_000)
    archive = request_resumable_archive(request, "verified-stream.zip")
    db_session.commit()
    build_archive(
        SimpleNamespace(job_id=archive.build_job_id, heartbeat=lambda *args: None, check_cancelled=lambda: None),
        archive.id,
    )
    db_session.refresh(archive)
    db_session.refresh(request)
    expected = (tmp_path / "cache" / archive.relative_path).read_bytes()
    application = LazyASGIApp()
    application._flask_app = app
    cookie = app.session_interface.get_signing_serializer(app).dumps({"_user_id": str(user.id)})

    async def download(*, range_header=None, interrupt=False):
        messages = []

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)
            if interrupt and message["type"] == "http.response.body" and message.get("body"):
                raise asyncio.CancelledError()

        headers = [(b"cookie", f"session={cookie}".encode())]
        if range_header:
            headers.append((b"range", range_header))
        try:
            await application._handle_download(
                {
                    "type": "http",
                    "method": "GET",
                    "path": f"/download_zip/{request.id}",
                    "scheme": "http",
                    "headers": headers,
                },
                receive,
                send,
            )
        except asyncio.CancelledError:
            pass
        return messages

    messages = asyncio.run(download(range_header=b"bytes=4-39"))
    assert messages[0]["status"] == 206
    assert b"".join(m.get("body", b"") for m in messages[1:]) == expected[4:40]
    interrupted = asyncio.run(download(interrupt=True))
    assert interrupted[0]["status"] == 200
    db_session.expire_all()
    transfers = db_session.scalars(
        select(DownloadTransfer).where(DownloadTransfer.download_request_id == request.id).order_by(DownloadTransfer.id)
    ).all()
    assert [t.status for t in transfers] == ["completed", "interrupted"]
    assert transfers[0].bytes_sent == 36
    assert download_lock_engine(db.engine).pool.checkedout() == 0
    # The interrupted stream released both admission and archive leases.
    again = asyncio.run(download(range_header=b"bytes=0-3"))
    assert again[0]["status"] == 206
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    with patch("asgi.acquire_archive_lease", side_effect=PoolTimeoutError()):
        busy = asyncio.run(download(range_header=b"bytes=0-3"))
    assert busy[0]["status"] == 503
    assert download_lock_engine(db.engine).pool.checkedout() == 0


def test_concurrent_streams_leave_sse_and_health_responsive(app, db_session, tmp_path):
    from sharewarez.models import Game, Library
    from sharewarez.platform import LibraryPlatform
    from sharewarez.live_sse import DownloadEventStream

    source = tmp_path / "concurrent.bin"
    source.write_bytes(b"a" * 3_000_000)
    app.config.update(DATA_FOLDER_WAREZ=str(tmp_path), BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS="")
    user = User(name=uuid4().hex, email=uuid4().hex + "@example.test", role="user", state=True, password_hash="unused")
    library = Library(name="Concurrent transfers", platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library])
    db_session.flush()
    game = Game(name="Concurrent ROM", library_uuid=library.uuid, full_disk_path=str(source))
    db_session.add(game)
    db_session.commit()
    user_id, game_uuid = user.id, game.uuid
    cookie = app.session_interface.get_signing_serializer(app).dumps({"_user_id": str(user_id)})
    headers = [(b"host", b"localhost"), (b"cookie", f"session={cookie}".encode())]
    db_session.remove()

    async def exercise():
        application = LazyASGIApp()
        application._flask_app = app
        paused = [asyncio.Event(), asyncio.Event()]
        release = asyncio.Event()

        async def receive():
            await asyncio.Event().wait()

        async def transfer(index):
            async def send(message):
                if message["type"] == "http.response.start":
                    assert message["status"] == 200
                if message["type"] == "http.response.body" and message.get("body"):
                    paused[index].set()
                    await release.wait()

            await application._handle_download(
                {
                    "type": "http",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/api/downloadrom/" + game_uuid,
                    "headers": headers,
                },
                receive,
                send,
            )

        tasks = [asyncio.create_task(transfer(i)) for i in range(2)]
        service = DownloadEventStream(app, interval=0.1, heartbeat=0.1)
        snapshot_received = asyncio.Event()

        async def send_event(message):
            if b"event: snapshot" in message.get("body", b""):
                snapshot_received.set()

        sse = None
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in paused)), 3)
            started = time.monotonic()
            sse = asyncio.create_task(
                service(
                    {
                        "type": "http",
                        "method": "GET",
                        "scheme": "http",
                        "headers": headers,
                        "query_string": b"view=downloads",
                    },
                    receive,
                    send_event,
                )
            )
            await asyncio.wait_for(snapshot_received.wait(), 2)

            def health():
                with app.test_client() as client:
                    return client.get("/health/live").status_code

            assert await asyncio.wait_for(asyncio.to_thread(health), 1) == 200
            print("CONCURRENT_SSE_HEALTH_MS", (time.monotonic() - started) * 1000)

            # A queued client disconnect must promptly remove its queue entry.
            async def disconnected():
                return {"type": "http.disconnect"}

            connected, slot = await application._admit_connected(disconnected, db.engine, user_id, 2, wait_seconds=5)
            assert not connected and slot is None
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await service.close()
            if sse:
                await sse

    asyncio.run(exercise())
    assert download_lock_engine(db.engine).pool.checkedout() == 0
    assert db_session.scalar(select(DownloadQueueEntry.id).where(DownloadQueueEntry.user_id == user_id)) is None
