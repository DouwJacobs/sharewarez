import asyncio
import time

from sqlalchemy import text


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
