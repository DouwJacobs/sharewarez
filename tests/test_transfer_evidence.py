import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from asgi import LazyASGIApp
from sharewarez.models import DownloadTransfer, User
from sharewarez.utils.download_limits import finish_transfer, mark_stale_transfers, reserve_transfer


@pytest.fixture
def owner(db_session):
    user = User(name=uuid4().hex, email=f'{uuid4().hex}@example.test', role='admin', password_hash='unused', state=True)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.mark.parametrize('failure,reason', [('read', 'source_read_error'), ('write', 'downstream_write_error')])
def test_observed_read_and_write_failures_persist_distinct_reasons(app, db_session, owner, tmp_path, monkeypatch, failure, reason):
    source = tmp_path / 'game.bin'
    source.write_bytes(b'abcdef')
    application = LazyASGIApp()
    application._flask_app = app

    async def chunks():
        yield b'ab'
        if failure == 'read':
            raise OSError('private source details must not reach the member')
        yield b'cdef'

    async def response(*args, **kwargs):
        return chunks(), {'content-length': '6'}

    monkeypatch.setattr('asgi.create_async_streaming_response', response)

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if failure == 'write' and message.get('body'):
            raise OSError('private downstream details')

    asyncio.run(application._stream_file(receive, send, str(source), source.name,
        {'headers': [], 'correlation_id': 'evidence-test-id'}, user_id=owner.id))
    db_session.expire_all()
    transfer = db_session.query(DownloadTransfer).filter_by(user_id=owner.id).one()
    assert transfer.status == 'interrupted' and transfer.end_reason == reason
    assert transfer.expected_response_bytes == 6
    assert transfer.delivery_kind == 'direct'
    assert transfer.correlation_id == 'evidence-test-id'
    assert transfer.bytes_sent == (2 if failure == 'read' else 0)


def test_first_terminal_reason_and_actor_survive_finalizer(app, db_session, owner):
    transfer_id, _, _ = reserve_transfer(owner.id, 'game.bin', 100, delivery_kind='direct', expected_response_bytes=100)
    assert finish_transfer(transfer_id, 10, 'cancelled', end_reason='admin_stop', ended_by_user_id=owner.id)
    assert not finish_transfer(transfer_id, 30, 'completed', end_reason='completed')
    db_session.expire_all()
    row = db_session.get(DownloadTransfer, transfer_id)
    assert row.end_reason == 'admin_stop' and row.ended_by_user_id == owner.id
    assert row.status == 'cancelled' and row.bytes_sent == row.reserved_bytes == 30


def test_stale_heartbeat_is_a_persistent_reason(app, db_session, owner):
    transfer_id, _, _ = reserve_transfer(owner.id, 'game.bin', 100)
    row = db_session.get(DownloadTransfer, transfer_id)
    row.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    db_session.commit()
    assert mark_stale_transfers() >= 1
    finish_transfer(transfer_id, 25, 'interrupted', end_reason='peer_disconnect')
    db_session.expire_all()
    row = db_session.get(DownloadTransfer, transfer_id)
    assert row.end_reason == 'stale_heartbeat' and row.bytes_sent == 25

def test_live_archive_generation_failure_has_unknown_response_length(app, db_session, owner, tmp_path, monkeypatch):
    application = LazyASGIApp()
    application._flask_app = app
    app.config['BASE_FOLDER_POSIX'] = str(tmp_path)
    (tmp_path / 'game.bin').write_bytes(b'data')

    async def chunks():
        yield b'zip prefix'
        raise ValueError('internal archive failure details')

    monkeypatch.setattr('asgi.async_generate_zipstream_response', lambda *args, **kwargs: (chunks(), {}))

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        pass

    asyncio.run(application._handle_streaming_download(receive, send, None, str(tmp_path), 'Game', str(tmp_path), owner.id, correlation_id='archive-evidence'))
    db_session.expire_all()
    row = db_session.query(DownloadTransfer).filter_by(user_id=owner.id).one()
    assert row.end_reason == 'archive_generation_error'
    assert row.delivery_kind == 'live_archive' and row.expected_response_bytes is None and row.http_status == 200
    assert row.bytes_sent == len(b'zip prefix')


def test_progress_store_failure_is_distinct(app, db_session, owner, tmp_path, monkeypatch):
    from sharewarez.utils.stream_control import TransferControl
    source = tmp_path / 'game.bin'
    source.write_bytes(b'data')
    application = LazyASGIApp()
    application._flask_app = app
    monkeypatch.setattr(TransferControl, 'PROGRESS_INTERVAL', 0)

    def fail(*args):
        raise RuntimeError('private database details')

    monkeypatch.setattr('asgi.update_transfer_progress', fail)

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        pass

    asyncio.run(application._stream_file(receive, send, str(source), source.name, {'headers': []}, user_id=owner.id))
    db_session.expire_all()
    row = db_session.query(DownloadTransfer).filter_by(user_id=owner.id).one()
    assert row.end_reason == 'progress_store_error' and row.status == 'interrupted'


@pytest.mark.parametrize('supplied', [b'valid-correlation', b'invalid request id'])
def test_ingress_rejection_logs_validated_correlation_without_attempt(app, db_session, monkeypatch, caplog, supplied):
    application = LazyASGIApp()
    application._flask_app = app

    async def unauthenticated(scope):
        return None

    monkeypatch.setattr(application, '_get_user_from_session', unauthenticated)
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        await asyncio.Event().wait()

    before = db_session.query(DownloadTransfer).count()
    asyncio.run(application._handle_download({'path': '/download_zip/123', 'method': 'GET', 'headers': [(b'x-request-id', supplied)]}, receive, send))
    assert messages[0]['status'] == 401
    observed = dict(messages[0]['headers'])[b'x-request-id'].decode()
    assert observed == 'valid-correlation' if supplied == b'valid-correlation' else len(observed) == 32
    assert db_session.query(DownloadTransfer).count() == before
    event = next(record for record in caplog.records if record.getMessage() == 'Download rejected')
    assert event.request_id == observed and event.path == '/download_zip/<download_id>'


def test_range_evidence_retains_original_expected_bytes(app, db_session, owner, tmp_path):
    source = tmp_path / 'game.bin'
    source.write_bytes(b'0123456789')
    application = LazyASGIApp()
    application._flask_app = app

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        pass

    asyncio.run(application._stream_file(receive, send, str(source), source.name,
        {'headers': [(b'range', b'bytes=3-6')], 'correlation_id': 'range-evidence'}, user_id=owner.id))
    db_session.expire_all()
    row = db_session.query(DownloadTransfer).filter_by(user_id=owner.id).one()
    assert row.expected_response_bytes == row.bytes_sent == 4
    assert row.range_start == 3 and row.range_end == 6 and row.http_status == 206
    assert row.end_reason == 'completed' and row.correlation_id == 'range-evidence'

def test_explicit_peer_disconnect_is_recorded(app, db_session, owner, tmp_path):
    source = tmp_path / 'game.bin'
    source.write_bytes(b'data')
    application = LazyASGIApp()
    application._flask_app = app

    queue = asyncio.Queue()

    async def receive():
        return await queue.get()

    async def send(message):
        if message['type'] == 'http.response.start':
            await queue.put({'type': 'http.disconnect'})
            await asyncio.sleep(0)

    asyncio.run(application._stream_file(receive, send, str(source), source.name, {'headers': []}, user_id=owner.id))
    db_session.expire_all()
    row = db_session.query(DownloadTransfer).filter_by(user_id=owner.id).one()
    assert row.end_reason == 'peer_disconnect' and row.status == 'interrupted'


def test_admin_endpoint_records_actor_and_cannot_replace_reason(app, client, db_session, owner):
    transfer_id, _, _ = reserve_transfer(owner.id, 'game.bin', 100)
    with client.session_transaction() as state:
        state['_user_id'] = str(owner.id)
        state['_fresh'] = True
    assert client.post(f'/admin/download-transfers/{transfer_id}/cancel').status_code == 302
    finish_transfer(transfer_id, 20, 'completed', end_reason='completed')
    db_session.expire_all()
    row = db_session.get(DownloadTransfer, transfer_id)
    assert row.status == 'cancelled' and row.end_reason == 'admin_stop' and row.ended_by_user_id == owner.id
    page = client.get('/admin/manage-downloads')
    assert b'Stopped by an administrator' in page.data


def test_concurrent_terminal_decisions_keep_winning_reason_and_max_bytes(app, db_session, owner):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    transfer_id, _, _ = reserve_transfer(owner.id, 'game.bin', 100)
    actor_id = owner.id
    barrier = Barrier(2)

    def finish(kind):
        with app.app_context():
            barrier.wait(timeout=10)
            if kind == 'admin_stop':
                return kind, finish_transfer(transfer_id, 10, 'cancelled', end_reason=kind, ended_by_user_id=actor_id)
            return kind, finish_transfer(transfer_id, 30, 'completed', end_reason=kind)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(finish, ['admin_stop', 'completed']))
    winner = [kind for kind, won in results if won]
    assert len(winner) == 1
    db_session.expire_all()
    row = db_session.get(DownloadTransfer, transfer_id)
    assert row.end_reason == winner[0] and row.bytes_sent == row.reserved_bytes == 30
    assert row.ended_by_user_id == (actor_id if winner[0] == 'admin_stop' else None)


def test_payload_and_history_render_unknown_historical_reason(app, client, db_session, owner):
    from sharewarez.live_snapshots import transfer_payload
    row = DownloadTransfer(user_id=owner.id, filename='legacy.bin', status='interrupted', bytes_sent=2, reserved_bytes=2)
    db_session.add(row)
    db_session.commit()
    payload = transfer_payload(row, datetime.now(timezone.utc), admin=True)
    assert payload['end_reason_label'] == 'Reason unavailable'
    assert payload['expected_response_bytes'] is None and payload['last_progress_at'] is None
    with client.session_transaction() as state:
        state['_user_id'] = str(owner.id)
    assert b'Reason unavailable' in client.get('/admin/manage-downloads').data

def test_progress_timestamp_advances_only_with_reported_bytes(app, db_session, owner):
    from sharewarez.utils.download_limits import update_transfer_progress
    transfer_id, _, _ = reserve_transfer(owner.id, 'game.bin', 100)
    row = db_session.get(DownloadTransfer, transfer_id)
    started_progress = row.last_progress_at
    update_transfer_progress(transfer_id, 0)
    db_session.refresh(row)
    assert row.last_progress_at == started_progress
    update_transfer_progress(transfer_id, 10)
    db_session.refresh(row)
    assert row.last_progress_at > started_progress
    progress = row.last_progress_at
    finish_transfer(transfer_id, 20, 'completed', end_reason='completed', ended_by_user_id=owner.id)
    db_session.refresh(row)
    assert row.last_progress_at > progress
    assert row.ended_by_user_id is None

def test_one_byte_attempt_is_not_rounded_to_zero(app, db_session, owner):
    from sharewarez.live_snapshots import transfer_payload
    from sharewarez.utils.download_state import attempt_payload
    attempt = DownloadTransfer(user_id=owner.id, filename='probe.bin', status='completed', bytes_sent=1,
        reserved_bytes=1, expected_response_bytes=1, delivery_kind='direct', http_status=206,range_start=0,range_end=0)
    db_session.add(attempt); db_session.commit()
    assert transfer_payload(attempt, datetime.now(timezone.utc), admin=True)['bytes_sent_label'] == '1 B'
    assert attempt_payload(attempt)['expected_bytes_label'] == '1 B'

@pytest.mark.parametrize('timestamp,expected', [
    (None, 'Not recorded'),
    (datetime(2026, 11, 6, 12), '2026-11-06 12:00:00 UTC'),
    (datetime(2026, 11, 6, 14, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2))),
     '2026-11-06 12:00:00.123456 UTC'),
])
def test_attempt_evidence_normalizes_timestamp_to_explicit_utc(timestamp, expected):
    from sharewarez.utils.transfer_evidence import utc_timestamp
    assert utc_timestamp(timestamp) == expected
