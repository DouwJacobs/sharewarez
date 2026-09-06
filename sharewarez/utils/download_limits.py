import asyncio
import time
import threading
from weakref import WeakKeyDictionary
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, case, delete, func, insert, select, text, update

from sqlalchemy.exc import TimeoutError, OperationalError

_LOCK_ENGINES = WeakKeyDictionary()
_LOCK_ENGINES_MUTEX = threading.Lock()


def download_lock_engine(engine):
    """Separate bounded lease connections from the application's request pool."""
    if engine.dialect.name != 'postgresql':
        return engine
    with _LOCK_ENGINES_MUTEX:
        dedicated = _LOCK_ENGINES.get(engine)
        if dedicated is None:
            dedicated = create_engine(engine.url, pool_size=32, max_overflow=0,
                                      pool_timeout=0.1, pool_pre_ping=True,
                                      connect_args={'connect_timeout': 3, 'options': '-c statement_timeout=2000'})
            _LOCK_ENGINES[engine] = dedicated
        return dedicated


async def run_owned_in_thread(operation, cleanup, on_cancel=None):
    """On cancellation, reclaim resources produced by an in-flight worker."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if on_cancel:
            on_cancel()
        # Cancellation must not abandon a connection/lease acquired after the
        # awaiter disappeared. Shield cleanup against repeated cancellation.
        async def reclaim():
            try:
                result = await task
                await asyncio.to_thread(cleanup, result)
            except Exception:
                pass
        cleanup_task = asyncio.create_task(reclaim())
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                continue
        raise


class DownloadSlot:
    """A cross-worker PostgreSQL advisory lock held for one transfer."""

    def __init__(self, connection, user_id, slot):
        self.connection = connection
        self.user_id = user_id
        self.slot = slot

    def release(self):
        if self.connection is None:
            return
        try:
            self.connection.execute(
                text("SELECT pg_advisory_unlock(:user_id, :slot)"),
                {"user_id": self.user_id, "slot": self.slot},
            )
        except BaseException:
            self.connection.invalidate()
            raise
        finally:
            self.connection.close()
            self.connection = None


def acquire_download_slot(engine, user_id, limit):
    """Claim one of a user's advisory-lock slots across all web workers."""
    connection = download_lock_engine(engine).connect()
    if connection.dialect.name != "postgresql":
        connection.close()
        return DownloadSlot(None, user_id, 0)
    try:
        for slot in range(limit):
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:user_id, :slot)"),
                {"user_id": user_id, "slot": slot},
            ).scalar()
            if acquired:
                connection.commit()
                return DownloadSlot(connection, user_id, slot)
        connection.close()
        return None
    except BaseException:
        connection.invalidate()
        connection.close()
        raise


async def acquire_queued_download_slot(
    engine, user_id, limit, *, request_id=None, priority=0, wait_seconds=10
):
    """Perform bounded fair admission off the event loop; reclaim on cancellation."""
    cancelled = threading.Event()
    def acquire():
        return _acquire_queued_slot(engine, user_id, limit, request_id, priority, wait_seconds, cancelled)
    def cleanup(slot):
        if slot is not None:
            slot.release()
    return await run_owned_in_thread(acquire, cleanup, on_cancel=cancelled.set)


def _acquire_queued_slot(engine, user_id, limit, request_id, priority, wait_seconds, cancelled):
    from sharewarez.models import DownloadQueueEntry
    table = DownloadQueueEntry.__table__
    queue_engine = download_lock_engine(engine)
    entry_id = None
    deadline = time.monotonic() + wait_seconds
    try:
        if engine.dialect.name != 'postgresql' or wait_seconds <= 0:
            return None if cancelled.is_set() else acquire_download_slot(engine, user_id, limit)
        now = datetime.now(timezone.utc)
        with queue_engine.begin() as connection:
            connection.execute(delete(table).where(table.c.expires_at <= now))
            entry_id = connection.execute(insert(table).values(
                token=str(uuid4()), user_id=user_id, download_request_id=request_id,
                priority=normalize_download_priority(priority), created_at=now,
                expires_at=now + timedelta(seconds=max(wait_seconds + 5, 30)),
            ).returning(table.c.id)).scalar_one()
        while not cancelled.is_set():
            with queue_engine.begin() as connection:
                first_id = connection.execute(select(table.c.id).where(
                    table.c.user_id == user_id, table.c.expires_at > datetime.now(timezone.utc)
                ).order_by(table.c.priority.desc(), table.c.created_at.asc(), table.c.id.asc()).limit(1)).scalar_one_or_none()
            if first_id == entry_id:
                slot = acquire_download_slot(engine, user_id, limit)
                if slot is not None:
                    return slot
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            cancelled.wait(min(0.15, remaining))
        return None
    except (TimeoutError, OperationalError):
        return None
    finally:
        if entry_id is not None:
            try:
                with queue_engine.begin() as connection:
                    connection.execute(delete(table).where(table.c.id == entry_id))
            except (TimeoutError, OperationalError):
                # Entries also expire and are swept by the next admission.
                pass


def normalize_download_priority(value):
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return 0
    return max(-10, min(priority, 10))


def calculate_download_expiry(settings_record=None, now=None):
    """Return a request expiry timestamp, or None when expiration is disabled."""
    settings = settings_record if isinstance(settings_record, dict) else getattr(settings_record, 'settings', None)
    hours = int((settings or {}).get('downloadRequestExpirationHours', 168) or 0)
    if hours <= 0:
        return None
    return (now or datetime.now(timezone.utc)) + timedelta(hours=min(hours, 8760))


async def throttle_chunks(chunks, megabits_per_second):
    """Pace an async byte stream to an average per-transfer bandwidth ceiling."""
    if not megabits_per_second:
        async for chunk in chunks:
            yield chunk
        return

    bytes_per_second = megabits_per_second * 1_000_000 / 8
    started = time.monotonic()
    sent = 0
    async for chunk in chunks:
        sent += len(chunk)
        delay = sent / bytes_per_second - (time.monotonic() - started)
        if delay > 0:
            await asyncio.sleep(delay)
        yield chunk


def estimate_path_bytes(path):
    target = Path(path)
    if target.is_file():
        return target.stat().st_size
    return sum(item.stat().st_size for item in target.rglob('*') if item.is_file())


def reserve_transfer(
    user_id, filename, expected_bytes, download_request_id=None, game_uuid=None,
    *, archive_id=None, range_start=None, range_end=None, http_status=None,
):
    """Atomically reserve monthly quota and create an active transfer record."""
    from sharewarez import db
    from sharewarez.models import DownloadRequest, DownloadTransfer, GlobalSettings, User

    user = db.session.execute(
        select(User).where(User.id == user_id).with_for_update()
    ).scalar_one()
    settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    settings = dict(settings_record.settings or {}) if settings_record else {}
    default_gb = float(settings.get('defaultMonthlyDownloadQuotaGb', 0) or 0)
    quota_bytes = user.monthly_download_quota_bytes
    if quota_bytes is None:
        quota_bytes = round(default_gb * 1_000_000_000)

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used_bytes = db.session.execute(
        select(func.coalesce(func.sum(DownloadTransfer.reserved_bytes), 0)).where(
            DownloadTransfer.user_id == user_id,
            DownloadTransfer.started_at >= month_start,
        )
    ).scalar_one()
    if quota_bytes and used_bytes + expected_bytes > quota_bytes:
        db.session.rollback()
        return None, used_bytes, quota_bytes

    if game_uuid is None and download_request_id is not None:
        game_uuid = db.session.scalar(
            select(DownloadRequest.game_uuid).where(DownloadRequest.id == download_request_id)
        )
    transfer = DownloadTransfer(
        user_id=user_id,
        download_request_id=download_request_id,
        game_uuid=game_uuid,
        filename=filename[:512],
        reserved_bytes=max(0, expected_bytes),
        status='active',
        last_activity_at=now,
        archive_id=archive_id,
        range_start=range_start,
        range_end=range_end,
        http_status=http_status,
        is_resumed=bool(range_start),
    )
    db.session.add(transfer)
    db.session.commit()
    from sharewarez.utils.download_notifications import notify_admin_repeat_download
    try:
        notify_admin_repeat_download(transfer)
    except Exception as error:
        from sharewarez.utils.event_logging import log_system_event
        log_system_event(
            f"Repeated download notification failed: {error}",
            event_type='notification', event_level='error', audit_user='system',
        )
    return transfer.id, used_bytes, quota_bytes


def finish_transfer(transfer_id, bytes_sent, status):
    from sharewarez import db
    from sharewarez.models import DownloadTransfer

    reported_bytes = max(0, bytes_sent)
    now = datetime.now(timezone.utc)
    result = db.session.execute(
        update(DownloadTransfer)
        .where(
            DownloadTransfer.id == transfer_id,
            DownloadTransfer.status == 'active',
        )
        .values(
            bytes_sent=reported_bytes,
            reserved_bytes=reported_bytes,
            status=status,
            last_activity_at=now,
            ended_at=now,
        )
    )
    if not result.rowcount:
        # Cancellation or stale-transfer cleanup may win the terminal-state
        # race. Preserve that state while reconciling bytes sent since the last
        # heartbeat so quota and audit totals do not under-report the stream.
        reconciled_bytes = case(
            (DownloadTransfer.bytes_sent < reported_bytes, reported_bytes),
            else_=DownloadTransfer.bytes_sent,
        )
        db.session.execute(
            update(DownloadTransfer)
            .where(
                DownloadTransfer.id == transfer_id,
                DownloadTransfer.status.in_(('cancelled', 'interrupted')),
            )
            .values(bytes_sent=reconciled_bytes, reserved_bytes=reconciled_bytes)
        )
    db.session.commit()
    return (result.rowcount or 0) > 0


def update_transfer_progress(transfer_id, bytes_sent):
    """Persist a lightweight heartbeat for active-transfer monitoring."""
    from sharewarez import db
    from sharewarez.models import DownloadTransfer

    result = db.session.execute(
        update(DownloadTransfer)
        .where(DownloadTransfer.id == transfer_id, DownloadTransfer.status == 'active')
        .values(bytes_sent=max(0, bytes_sent), last_activity_at=datetime.now(timezone.utc))
    )
    db.session.commit()
    return result.rowcount > 0


def mark_stale_transfers(stale_seconds=60):
    """Close active rows whose worker stopped heartbeating."""
    from sharewarez import db
    from sharewarez.models import DownloadTransfer

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=stale_seconds)
    result = db.session.execute(
        update(DownloadTransfer)
        .where(
            DownloadTransfer.status == 'active',
            DownloadTransfer.last_activity_at < cutoff,
        )
        .values(
            status='interrupted',
            reserved_bytes=DownloadTransfer.bytes_sent,
            ended_at=now,
        )
    )
    if result.rowcount:
        db.session.commit()
    else:
        db.session.rollback()
    return result.rowcount


def expire_download_requests(user_id=None):
    """Mark elapsed available links expired before presenting or serving them."""
    from sharewarez import db
    from sharewarez.models import DownloadRequest

    statement = (
        update(DownloadRequest)
        .where(
            DownloadRequest.status == 'available',
            DownloadRequest.expires_at.is_not(None),
            DownloadRequest.expires_at <= datetime.now(timezone.utc),
        )
        .values(status='expired')
    )
    if user_id is not None:
        statement = statement.where(DownloadRequest.user_id == user_id)
    result = db.session.execute(statement)
    db.session.commit()
    return result.rowcount
