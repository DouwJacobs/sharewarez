import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, text


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
        finally:
            self.connection.close()
            self.connection = None


def acquire_download_slot(engine, user_id, limit):
    """Claim one of a user's advisory-lock slots across all web workers."""
    connection = engine.connect()
    if connection.dialect.name != "postgresql":
        connection.close()
        return DownloadSlot(None, user_id, 0)
    for slot in range(limit):
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:user_id, :slot)"),
            {"user_id": user_id, "slot": slot},
        ).scalar()
        if acquired:
            return DownloadSlot(connection, user_id, slot)
    connection.close()
    return None


async def acquire_queued_download_slot(
    engine, user_id, limit, *, request_id=None, priority=0, wait_seconds=10
):
    """Wait fairly for a per-user slot, admitting higher priority requests first."""
    if engine.dialect.name != "postgresql" or wait_seconds <= 0:
        return acquire_download_slot(engine, user_id, limit)

    from sharewarez.models import DownloadQueueEntry

    table = DownloadQueueEntry.__table__
    token = str(uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(wait_seconds + 5, 30))
    with engine.begin() as connection:
        connection.execute(delete(table).where(table.c.expires_at <= now))
        entry_id = connection.execute(
            insert(table).values(
                token=token,
                user_id=user_id,
                download_request_id=request_id,
                priority=normalize_download_priority(priority),
                created_at=now,
                expires_at=expires_at,
            ).returning(table.c.id)
        ).scalar_one()

    deadline = time.monotonic() + wait_seconds
    try:
        while True:
            with engine.begin() as connection:
                first_id = connection.execute(
                    select(table.c.id)
                    .where(table.c.user_id == user_id, table.c.expires_at > datetime.now(timezone.utc))
                    .order_by(table.c.priority.desc(), table.c.created_at.asc(), table.c.id.asc())
                    .limit(1)
                ).scalar_one_or_none()
            if first_id == entry_id:
                slot = acquire_download_slot(engine, user_id, limit)
                if slot is not None:
                    return slot
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.15)
    finally:
        with engine.begin() as connection:
            connection.execute(delete(table).where(table.c.id == entry_id))


def normalize_download_priority(value):
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return 0
    return max(-10, min(priority, 10))


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


def reserve_transfer(user_id, filename, expected_bytes, download_request_id=None):
    """Atomically reserve monthly quota and create an active transfer record."""
    from sharewarez import db
    from sharewarez.models import DownloadTransfer, GlobalSettings, User

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

    transfer = DownloadTransfer(
        user_id=user_id,
        download_request_id=download_request_id,
        filename=filename[:512],
        reserved_bytes=max(0, expected_bytes),
        status='active',
    )
    db.session.add(transfer)
    db.session.commit()
    return transfer.id, used_bytes, quota_bytes


def finish_transfer(transfer_id, bytes_sent, status):
    from sharewarez import db
    from sharewarez.models import DownloadTransfer

    transfer = db.session.get(DownloadTransfer, transfer_id)
    if transfer is None:
        return
    transfer.bytes_sent = max(0, bytes_sent)
    transfer.reserved_bytes = transfer.bytes_sent
    transfer.status = status
    transfer.ended_at = datetime.now(timezone.utc)
    db.session.commit()
