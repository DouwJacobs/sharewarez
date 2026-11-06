import asyncio

import pytest

from asgi import LazyASGIApp
from sharewarez.async_streaming import async_generate_file_chunks


def test_short_fixed_length_source_is_an_error(tmp_path):
    source = tmp_path / 'short.bin'
    source.write_bytes(b'short')

    async def collect():
        return b''.join([part async for part in async_generate_file_chunks(str(source), length=10)])

    with pytest.raises(OSError):
        asyncio.run(collect())


def test_response_headers_and_body_use_the_same_open_file(tmp_path):
    source = tmp_path / 'original.bin'
    original = b'original representation'
    source.write_bytes(original)
    replacement = tmp_path / 'replacement.bin'
    replacement.write_bytes(b'replaced representation with different content')
    messages = []

    async def send(message):
        messages.append(message)
        if message['type'] == 'http.response.start':
            replacement.replace(source)

    async def receive():
        await asyncio.Event().wait()

    asyncio.run(LazyASGIApp()._stream_file(receive, send, str(source), source.name, {'headers': []}))
    assert int(dict(messages[0]['headers'])[b'content-length']) == len(original)
    assert b''.join(message.get('body', b'') for message in messages) == original

class ManualClock:
    def __init__(self):
        self.value = 0
        self.waiters = []

    def now(self):
        return self.value

    async def sleep(self, delay):
        if delay <= 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.value + delay, future))
        try:
            await future
        finally:
            self.waiters = [(deadline, item) for deadline, item in self.waiters if item is not future]

    async def advance(self, seconds):
        self.value += seconds
        for deadline, future in list(self.waiters):
            if deadline <= self.value and not future.done():
                future.set_result(None)
        for _ in range(10):
            await asyncio.sleep(0)


async def settle(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 3)


def test_live_owner_survives_old_stale_cutoff_while_io_waits():
    from sharewarez.utils.stream_control import TransferControl

    async def exercise():
        clock, calls = ManualClock(), []
        queue = asyncio.Queue()
        control = TransferControl(queue.get, lambda identity: calls.append(clock.now()) or True, lambda *args: True, clock=clock)
        control.start(7)
        pending = asyncio.create_task(control.wait(asyncio.Event().wait()))
        await asyncio.sleep(0)
        for instant in range(10, 80, 10):
            await clock.advance(10)
            try:
                await settle(lambda: control.last_authority == instant)
            except TimeoutError:
                raise AssertionError((instant, control.last_authority, control.reason, clock.waiters))
            await settle(lambda: any(deadline == instant + 10 and not future.done() for deadline, future in clock.waiters))
            assert not pending.done() and not control.stopped.is_set()
        assert calls == list(range(10, 80, 10))
        await queue.put({'type': 'http.disconnect'})
        with pytest.raises(Exception, match='Connection closed by peer'):
            await pending
        await control.close()
        assert control.watcher.done() and control.owner_task.done()

    asyncio.run(exercise())


def test_io_idle_deadline_is_five_minutes():
    from sharewarez.utils.stream_control import TransferControl
    from sharewarez.utils.transfer_evidence import TransferFailure

    async def exercise():
        clock = ManualClock()
        control = TransferControl(asyncio.Queue().get, lambda *args: True, lambda *args: True, clock=clock)
        pending = asyncio.create_task(control.wait(asyncio.Event().wait()))
        await settle(lambda: len(clock.waiters) >= 1)
        await clock.advance(299)
        assert not pending.done()
        await clock.advance(1)
        with pytest.raises(TransferFailure) as error:
            await pending
        assert error.value.reason == 'stall_timeout'
        await control.close()
    asyncio.run(exercise())


def test_planned_slow_pacing_is_outside_io_timeout_and_wakes_on_disconnect():
    from sharewarez.utils.stream_control import TransferControl
    from sharewarez.utils.transfer_evidence import TransferFailure

    async def exercise():
        clock = ManualClock()
        queue = asyncio.Queue()
        control = TransferControl(queue.get, lambda *args: True, lambda *args: True, clock=clock)
        control.start(7)
        pacing = asyncio.create_task(control.pace(75_000_000, 1))  # 600 seconds at 1 Mbps.
        await settle(lambda: any(deadline == 10 and not future.done() for deadline, future in clock.waiters))
        for instant in range(10, 320, 10):
            await clock.advance(10)
            try:
                await settle(lambda: control.last_authority == instant)
            except TimeoutError:
                raise AssertionError((instant, control.last_authority, control.reason, clock.waiters))
            await settle(lambda: any(deadline == instant + 10 and not future.done() for deadline, future in clock.waiters))
        assert not pacing.done() and not control.stopped.is_set()
        await queue.put({'type': 'http.disconnect'})
        with pytest.raises(TransferFailure) as error:
            await pacing
        assert error.value.reason == 'peer_disconnect'
        await control.close()
    asyncio.run(exercise())


def test_heartbeat_retries_transient_error_but_stops_at_stale_deadline():
    from sharewarez.utils.stream_control import TransferControl

    async def exercise(recover):
        clock, calls = ManualClock(), []
        def heartbeat(identity):
            calls.append(clock.now())
            if not recover or len(calls) == 1:
                raise RuntimeError('bookkeeping temporarily unavailable')
            return True
        control = TransferControl(asyncio.Queue().get, heartbeat, lambda *args: True, clock=clock)
        control.start(7)
        await asyncio.sleep(0)
        for instant in range(10, 70, 10):
            await clock.advance(10)
            if instant < 60 or recover:
                await settle(lambda: len(calls) >= instant // 10)
                await settle(lambda: control.pending_heartbeat is None)
                await settle(lambda: any(deadline == instant + 10 and not future.done() for deadline, future in clock.waiters))
        if recover:
            assert control.last_authority == 60 and not control.stopped.is_set()
        else:
            assert control.stopped.is_set() and control.reason == 'progress_store_error'
            assert calls == [10, 20, 30, 40, 50]
        await control.close()
    asyncio.run(exercise(True))
    asyncio.run(exercise(False))


@pytest.mark.parametrize('phase', ['read', 'send', 'pace'])
def test_authoritative_stop_wakes_every_wait(phase):
    from sharewarez.utils.stream_control import TransferControl
    from sharewarez.utils.transfer_evidence import TransferFailure

    async def exercise():
        clock = ManualClock()
        control = TransferControl(asyncio.Queue().get, lambda *args: False, lambda *args: True, clock=clock)
        control.start(7)
        operation = control.pace(1_000_000, 0.001) if phase == 'pace' else control.wait(asyncio.Event().wait())
        pending = asyncio.create_task(operation)
        await settle(lambda: len(clock.waiters) >= 2)
        await clock.advance(10)
        with pytest.raises(TransferFailure):
            await asyncio.wait_for(pending, 3)
        assert control.stopped.is_set()
        await control.close()
    asyncio.run(exercise())


def test_cancelled_blocking_read_keeps_resource_until_it_returns_and_closes_once():
    import threading
    from sharewarez.utils.stream_io import ThreadResource, _CLEANUPS

    async def exercise():
        entered, release = threading.Event(), threading.Event()
        class Resource:
            closes = 0
            def close(self):
                self.closes += 1
        resource = Resource()
        owned = ThreadResource(resource)
        def read(value):
            entered.set()
            release.wait(3)
            assert value.closes == 0
            return b'data'
        task = asyncio.create_task(owned.call(read))
        await settle(entered.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await owned.aclose()
        assert resource.closes == 0
        release.set()
        await settle(lambda: not _CLEANUPS)
        await owned.aclose()
        assert resource.closes == 1
    asyncio.run(exercise())

@pytest.mark.parametrize('kind', ['direct', 'live_archive'])
@pytest.mark.parametrize('phase', ['read', 'send'])
@pytest.mark.parametrize('outcome', ['complete', 'admin_stop'])
def test_both_streaming_paths_heartbeat_during_io_and_release_on_stop(app, db_session, tmp_path, monkeypatch, kind, phase, outcome):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from sharewarez.models import DownloadTransfer, User
    from sharewarez.utils.download_limits import finish_transfer, mark_stale_transfers
    from sharewarez.utils.stream_control import TransferControl
    user = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='admin', password_hash='unused', state=True)
    db_session.add(user)
    db_session.commit()
    uid = user.id
    source = tmp_path / 'game.bin'
    source.write_bytes(b'data')
    app.config['BASE_FOLDER_POSIX'] = str(tmp_path)
    application = LazyASGIApp()
    application._flask_app = app

    async def exercise():
        clock, controls = ManualClock(), []
        entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        def factory(*args, **kwargs):
            control = TransferControl(*args, **kwargs, clock=clock)
            controls.append(control)
            return control
        monkeypatch.setattr('asgi.TransferControl', factory)
        async def chunks():
            try:
                if phase == 'read':
                    entered.set()
                    await release.wait()
                yield b'data'
            finally:
                closed.set()
        async def direct_response(*args, **kwargs):
            return chunks(), {'content-length': '4'}
        monkeypatch.setattr('asgi.create_async_streaming_response', direct_response)
        monkeypatch.setattr('asgi.async_generate_zipstream_response', lambda *args, **kwargs: (chunks(), {}))
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            if phase == 'send' and message.get('body'):
                entered.set()
                await release.wait()
        if kind == 'direct':
            task = asyncio.create_task(application._stream_file(receive, send, str(source), source.name, {'headers': []}, user_id=uid))
        else:
            task = asyncio.create_task(application._handle_streaming_download(receive, send, None, str(tmp_path), 'Game', str(tmp_path), uid))
        await asyncio.wait_for(entered.wait(), 3)
        control = controls[0]
        row = db_session.query(DownloadTransfer).filter_by(user_id=uid).one()
        initial_progress = row.last_progress_at
        row.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=61)
        db_session.commit()
        for instant in range(10, 80, 10):
            await clock.advance(10)
            await settle(lambda: control.last_authority == instant)
            await settle(lambda: any(deadline == instant + 10 and not future.done() for deadline, future in clock.waiters))
            assert not task.done()
        assert mark_stale_transfers() == 0
        db_session.refresh(row)
        assert row.status == 'active' and row.bytes_sent == 0
        assert row.last_progress_at == initial_progress and row.last_activity_at > initial_progress
        if outcome == 'complete':
            release.set()
        else:
            finish_transfer(row.id, 0, 'cancelled', end_reason='admin_stop', ended_by_user_id=uid)
            await clock.advance(10)
        await asyncio.wait_for(task, 3)
        assert closed.is_set() and control.watcher.done() and control.owner_task.done()
        db_session.refresh(row)
        assert row.end_reason == ('completed' if outcome == 'complete' else 'admin_stop')
        assert row.bytes_sent == row.reserved_bytes == (4 if outcome == 'complete' else 0)
    asyncio.run(exercise())

@pytest.fixture
def stream_owner(db_session):
    from uuid import uuid4
    from sharewarez.models import User
    user = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='user', password_hash='unused', state=True)
    db_session.add(user)
    db_session.commit()
    return user


def test_truncated_file_cannot_complete_its_promised_response(app, db_session, stream_owner, tmp_path):
    from sharewarez.models import DownloadTransfer
    source = tmp_path / 'truncated.bin'
    source.write_bytes(b'x' * 100)
    application = LazyASGIApp()
    application._flask_app = app
    messages = []
    async def receive():
        await asyncio.Event().wait()
    async def send(message):
        messages.append(message)
        if message['type'] == 'http.response.start':
            source.write_bytes(b'x' * 20)
    asyncio.run(application._stream_file(receive, send, str(source), source.name, {'headers': []}, user_id=stream_owner.id))
    db_session.expire_all()
    row = db_session.query(DownloadTransfer).filter_by(user_id=stream_owner.id).one()
    assert row.status == 'interrupted' and row.end_reason == 'source_read_error'
    assert row.expected_response_bytes == 100 and row.bytes_sent == row.reserved_bytes == 20
    assert not any(message.get('more_body') is False for message in messages)
    assert sum(message['type'] == 'http.response.start' for message in messages) == 1


@pytest.mark.parametrize('kind', ['direct', 'cached_archive'])
def test_interrupted_plus_resumed_representation_hash_and_resource_release(app, db_session, tmp_path, monkeypatch, kind):
    import hashlib
    from types import SimpleNamespace
    from sqlalchemy import text
    from sharewarez import db
    from sharewarez.models import DownloadQueueEntry, DownloadTransfer
    from sharewarez.utils.download_cache import request_resumable_archive, build_archive, resolved_archive_path
    from sharewarez.utils.download_limits import download_lock_engine
    from sharewarez.utils.stream_io import FileSource
    from tests.test_download_cache import _cache_download_fixture
    source, user, game, link = _cache_download_fixture(db_session, app, tmp_path, suffix=kind)
    payload = bytes(range(251)) * 20_000
    (source / 'payload.bin').write_bytes(payload)
    if kind == 'cached_archive':
        archive = request_resumable_archive(link, 'verified.zip')
        db_session.commit()
        build_archive(SimpleNamespace(job_id=archive.build_job_id, heartbeat=lambda *args: None, check_cancelled=lambda: None), archive.id)
        db_session.refresh(archive)
        expected = resolved_archive_path(archive).read_bytes()
    else:
        link.file_location = link.zip_file_path = str(source / 'payload.bin')
        link.status, link.delivery_kind = 'available', 'direct'
        db_session.commit()
        expected = payload
    application = LazyASGIApp()
    application._flask_app = app
    cookie = app.session_interface.get_signing_serializer(app).dumps({'_user_id': str(user.id)})
    handles = []
    original_open = FileSource.open
    async def capture(path):
        owned = await original_open(path)
        handles.append(owned.resource)
        return owned
    monkeypatch.setattr(FileSource, 'open', capture)

    async def request(start=None, interrupt=False):
        queue, messages = asyncio.Queue(), []
        async def receive():
            return await queue.get()
        async def send(message):
            messages.append(message)
            if interrupt and message.get('body'):
                await queue.put({'type': 'http.disconnect'})
                await asyncio.sleep(0)
        headers = [(b'cookie', f'session={cookie}'.encode())]
        if start is not None:
            headers.append((b'range', f'bytes={start}-'.encode()))
        await application._handle_download({'type': 'http', 'method': 'GET', 'path': f'/download_zip/{link.id}', 'scheme': 'http', 'headers': headers}, receive, send)
        return messages, b''.join(message.get('body', b'') for message in messages)
    first_messages, prefix = asyncio.run(request(interrupt=True))
    assert 0 < len(prefix) < len(expected)
    resumed_messages, suffix = asyncio.run(request(start=len(prefix)))
    assert resumed_messages[0]['status'] == 206
    assert dict(first_messages[0]['headers'])[b'etag'] == dict(resumed_messages[0]['headers'])[b'etag']
    assert hashlib.sha256(prefix + suffix).digest() == hashlib.sha256(expected).digest()
    db_session.expire_all()
    attempts = db_session.query(DownloadTransfer).filter_by(download_request_id=link.id).order_by(DownloadTransfer.id).all()
    assert len(attempts) == 2
    assert attempts[0].end_reason == 'peer_disconnect' and attempts[0].bytes_sent == len(prefix)
    assert attempts[1].end_reason == 'completed' and attempts[1].expected_response_bytes == len(suffix)
    assert sum(row.reserved_bytes for row in attempts) == len(expected)
    assert all(handle.closed for handle in handles) and len(handles) == 2
    assert download_lock_engine(db.engine).pool.checkedout() == 0
    assert db_session.query(DownloadQueueEntry).filter_by(user_id=user.id).count() == 0
    assert db_session.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND (classid=:uid OR classid=139822755)"), {'uid': user.id}).scalar_one() == 0


def test_cancelled_open_reclaims_late_resource_once():
    import threading
    from sharewarez.utils.stream_io import ThreadResource, _CLEANUPS
    async def exercise():
        entered, release = threading.Event(), threading.Event()
        class Resource:
            closes = 0
            def close(self):
                self.closes += 1
        resource = Resource()
        def factory():
            entered.set()
            release.wait(3)
            return resource
        task = asyncio.create_task(ThreadResource.create(factory))
        await settle(entered.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await settle(lambda: not _CLEANUPS)
        assert resource.closes == 1
    asyncio.run(exercise())


def test_byte_progress_has_independent_one_second_cadence():
    from sharewarez.utils.stream_control import TransferControl
    async def exercise():
        clock, records = ManualClock(), []
        control = TransferControl(asyncio.Queue().get, lambda *args: True, lambda _, count: records.append((clock.now(), count)) or True, clock=clock)
        control.start(7)
        await control.progress(4)
        await clock.advance(0.5)
        await control.progress(8)
        assert records == []
        await clock.advance(0.5)
        await control.progress(12)
        await clock.advance(0.5)
        await control.progress(16)
        assert records == [(1, 12)]
        await clock.advance(0.5)
        await control.progress(20)
        assert records == [(1, 12), (2, 20)]
        await control.close()
    asyncio.run(exercise())

def test_full_reader_executor_does_not_starve_ownership_or_bookkeeping_cleanup():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sharewarez.utils.stream_control import BOOKKEEPING_EXECUTOR, TransferControl
    from sharewarez.utils.download_limits import run_owned_in_thread
    async def exercise():
        reader_pool = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(reader_pool)
        entered, release = threading.Event(), threading.Event()
        def blocked_read():
            entered.set()
            release.wait(3)
        reader = asyncio.create_task(asyncio.to_thread(blocked_read))
        await settle(entered.is_set)
        clock = ManualClock()
        control = TransferControl(asyncio.Queue().get, lambda *args: True, lambda *args: True, clock=clock)
        control.start(7)
        try:
            await settle(lambda: any(deadline == 10 and not future.done() for deadline, future in clock.waiters))
            await clock.advance(10)
            await settle(lambda: control.last_authority == 10)
            cleaned = []
            result = await asyncio.wait_for(run_owned_in_thread(lambda: cleaned.append('quota/slot') or 'released', lambda _: None, executor=BOOKKEEPING_EXECUTOR), 1)
            assert result == 'released' and cleaned == ['quota/slot'] and not reader.done()
        finally:
            await control.close()
            release.set()
            await reader
    asyncio.run(exercise())


def test_hanging_bookkeeping_stops_before_stale_deadline_without_overlap():
    import threading
    from sharewarez.utils.stream_control import TransferControl
    async def exercise():
        release = threading.Event()
        clock, calls = ManualClock(), []
        def heartbeat(identity):
            calls.append(clock.now())
            release.wait(3)
            return True
        control = TransferControl(asyncio.Queue().get, heartbeat, lambda *args: True, clock=clock)
        control.start(7)
        await settle(lambda: any(deadline == 10 and not future.done() for deadline, future in clock.waiters))
        await clock.advance(10)
        await settle(lambda: len(calls) == 1)
        try:
            for instant in range(20, 70, 10):
                await settle(lambda: any(deadline <= instant and not future.done() for deadline, future in clock.waiters))
                await clock.advance(10)
            assert control.stopped.is_set() and control.reason == 'progress_store_error'
            assert calls == [10]
        finally:
            release.set()
            await control.close()
    asyncio.run(exercise())

def test_repeated_task_cancellation_finishes_once_and_closes_descriptor(app, db_session, stream_owner, tmp_path, monkeypatch):
    import threading
    from sharewarez.models import DownloadTransfer
    from sharewarez.utils.stream_io import FileSource
    from sharewarez.utils.stream_control import TransferControl
    source = tmp_path / 'game.bin'
    source.write_bytes(b'data')
    application = LazyASGIApp()
    application._flask_app = app
    entered_finalizer, release_finalizer = threading.Event(), threading.Event()
    calls, handles, controls = [], [], []
    original_finish, original_open = application._sync_finish_transfer, FileSource.open
    def finish(*args):
        calls.append(args)
        entered_finalizer.set()
        release_finalizer.wait(3)
        original_finish(*args)
    async def capture(path):
        owned = await original_open(path)
        handles.append(owned.resource)
        return owned
    def factory(*args, **kwargs):
        control = TransferControl(*args, **kwargs)
        controls.append(control)
        return control
    monkeypatch.setattr(application, '_sync_finish_transfer', finish)
    monkeypatch.setattr(FileSource, 'open', capture)
    monkeypatch.setattr('asgi.TransferControl', factory)
    async def exercise():
        entered_send = asyncio.Event()
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            if message.get('body'):
                entered_send.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(application._stream_file(receive, send, str(source), source.name, {'headers': []}, user_id=stream_owner.id))
        await asyncio.wait_for(entered_send.wait(), 3)
        task.cancel()
        await settle(entered_finalizer.is_set)
        task.cancel()
        release_finalizer.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1 and all(handle.closed for handle in handles)
        assert controls[0].watcher.done() and controls[0].owner_task.done()
    asyncio.run(exercise())
    db_session.expire_all()
    row = db_session.query(DownloadTransfer).filter_by(user_id=stream_owner.id).one()
    assert row.status == 'interrupted' and row.end_reason == 'unknown' and row.reserved_bytes == 0

def test_late_handler_failure_releases_slot_without_second_response(app, monkeypatch):
    application = LazyASGIApp()
    application._flask_app = app
    messages, released = [], []
    class Slot:
        def release(self):
            released.append(True)
    async def user(scope):
        return 123
    async def admit(*args, **kwargs):
        return True, Slot()
    async def handler(scope, receive, send, *args):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        raise RuntimeError('late finalizer failed')
    monkeypatch.setattr(application, '_get_user_from_session', user)
    monkeypatch.setattr(application, '_sync_download_settings', lambda *args: (None, 2, 0, 0, None, 0))
    monkeypatch.setattr(application, '_admit_connected', admit)
    monkeypatch.setattr(application, '_handle_zip_download', handler)
    async def receive():
        await asyncio.Event().wait()
    async def send(message):
        messages.append(message)
    with pytest.raises(RuntimeError, match='late finalizer failed'):
        asyncio.run(application._handle_download({'method': 'GET', 'path': '/download_zip/123', 'headers': []}, receive, send))
    assert released == [True]
    assert len(messages) == 1 and messages[0]['status'] == 200

def test_receive_failure_stops_wait_without_claiming_peer_cause():
    from sharewarez.utils.stream_control import TransferControl
    from sharewarez.utils.transfer_evidence import TransferFailure
    async def exercise():
        async def receive():
            raise RuntimeError('receive channel failed')
        control = TransferControl(receive, lambda *args: True, lambda *args: True)
        with pytest.raises(TransferFailure) as error:
            await asyncio.wait_for(control.wait(asyncio.Event().wait()), 1)
        assert error.value.reason == 'unknown'
        await control.close()
    asyncio.run(exercise())