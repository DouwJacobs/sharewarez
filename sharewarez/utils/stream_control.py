"""Transfer-owned liveness and cancellable I/O; pacing has a separate budget."""
import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
import time

from sharewarez.utils.transfer_evidence import TransferFailure


BOOKKEEPING_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix='download-owner')


class SystemClock:
    now = staticmethod(time.monotonic)
    sleep = staticmethod(asyncio.sleep)


async def finish_cleanup(operation):
    """Finish the complete resource finalizer even after repeated cancellation."""
    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class TransferControl:
    HEARTBEAT_INTERVAL = 10
    STALE_SECONDS = 60
    IO_IDLE_SECONDS = 300
    PROGRESS_INTERVAL = 1
    PACE_SLICE_SECONDS = 0.25

    def __init__(self, receive, heartbeat, progress, *, clock=None):
        self.clock = clock or SystemClock()
        self.heartbeat = heartbeat
        self.store_progress = progress
        self.stopped = asyncio.Event()
        self.reason = 'unknown'
        self.transfer_id = None
        self.owner_task = None
        self.pending_heartbeat = None
        self.last_authority = self.clock.now()
        self.last_progress_store = self.last_authority
        self.started = self.last_authority
        self.paced_bytes = 0
        self.watcher = asyncio.create_task(self._watch(receive))

    async def _watch(self, receive):
        try:
            while not self.stopped.is_set():
                message = await receive()
                if message.get('type') == 'http.disconnect':
                    self.stop('peer_disconnect')
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            self.stop('unknown')

    def stop(self, reason):
        if not self.stopped.is_set():
            self.reason = reason
            self.stopped.set()

    def start(self, transfer_id):
        self.transfer_id = transfer_id
        self.started = self.clock.now()
        self.last_authority = self.clock.now()
        if transfer_id is not None:
            self.owner_task = asyncio.create_task(self._own())

    async def _own(self):
        try:
            while not self.stopped.is_set():
                if self.pending_heartbeat is None:
                    await self.clock.sleep(self.HEARTBEAT_INTERVAL)
                    if self.clock.now() - self.last_authority >= self.STALE_SECONDS:
                        self.stop('progress_store_error')
                        return
                    self.pending_heartbeat = asyncio.get_running_loop().run_in_executor(BOOKKEEPING_EXECUTOR, self.heartbeat, self.transfer_id)
                remaining = self.STALE_SECONDS - (self.clock.now() - self.last_authority)
                timer = asyncio.create_task(self.clock.sleep(min(self.HEARTBEAT_INTERVAL, max(0, remaining))))
                try:
                    await asyncio.wait((self.pending_heartbeat, timer), return_when=asyncio.FIRST_COMPLETED)
                    if self.pending_heartbeat.done():
                        pending, self.pending_heartbeat = self.pending_heartbeat, None
                        try:
                            active = pending.result()
                        except Exception:
                            active = None
                        if active is False:
                            self.stop('unknown')
                            return
                        if active:
                            self.last_authority = self.clock.now()
                    if self.clock.now() - self.last_authority >= self.STALE_SECONDS:
                        self.stop('progress_store_error')
                        return
                finally:
                    timer.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await timer
        except asyncio.CancelledError:
            raise

    async def wait(self, operation, *, io=True):
        if self.stopped.is_set():
            closer = getattr(operation, 'close', None)
            if closer:
                closer()
            elif isinstance(operation, asyncio.Future):
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
            raise TransferFailure(self.reason)
        task = asyncio.ensure_future(operation)
        stopped = asyncio.create_task(self.stopped.wait())
        timer = asyncio.create_task(self.clock.sleep(self.IO_IDLE_SECONDS)) if io else None
        try:
            await asyncio.wait([task, stopped, *([timer] if timer else [])], return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                return task.result()
            if self.stopped.is_set():
                raise TransferFailure(self.reason)
            raise TransferFailure('stall_timeout')
        finally:
            for pending in (task, stopped, timer):
                if pending is not None and not pending.done():
                    pending.cancel()
            await finish_cleanup(asyncio.gather(task, stopped, *([timer] if timer else []), return_exceptions=True))

    def check(self):
        if self.stopped.is_set():
            raise TransferFailure(self.reason)

    async def pace(self, size, megabits_per_second):
        self.check()
        if not megabits_per_second:
            return
        self.paced_bytes += size
        deadline = self.started + self.paced_bytes / (megabits_per_second * 1_000_000 / 8)
        while (delay := deadline - self.clock.now()) > 0:
            await self.wait(self.clock.sleep(min(delay, self.PACE_SLICE_SECONDS)), io=False)
            self.check()

    async def progress(self, bytes_sent):
        if self.transfer_id is None or self.clock.now() - self.last_progress_store < self.PROGRESS_INTERVAL:
            return
        try:
            active = await self.wait(asyncio.get_running_loop().run_in_executor(BOOKKEEPING_EXECUTOR, self.store_progress, self.transfer_id, bytes_sent))
        except TransferFailure:
            raise
        except Exception as exc:
            raise TransferFailure('progress_store_error') from exc
        if not active:
            self.stop('unknown')
            self.check()
        self.last_progress_store = self.clock.now()

    async def close(self):
        for task in (self.owner_task, self.watcher, self.pending_heartbeat):
            if task is not None:
                task.cancel()
        await asyncio.gather(*[task for task in (self.owner_task, self.watcher, self.pending_heartbeat) if task is not None], return_exceptions=True)