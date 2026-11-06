"""Own blocking I/O resources even when their async consumer is cancelled."""
import asyncio
import os
import logging
from concurrent.futures import ThreadPoolExecutor

_CLEANUPS: set[asyncio.Task] = set()
_CLOSE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='download-close')


def _defer(coroutine):
    task = asyncio.create_task(coroutine)
    _CLEANUPS.add(task)

    def finished(done):
        _CLEANUPS.discard(done)
        if not done.cancelled():
            error = done.exception()
            if error:
                logging.getLogger(__name__).error('Deferred stream cleanup failed: %s', type(error).__name__)
    task.add_done_callback(finished)
    return task


async def _settle(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


def _close(resource):
    closer = getattr(resource, 'close', None)
    if closer:
        closer()


class ThreadResource:
    def __init__(self, resource):
        self.resource = resource
        self.pending = None
        self.closing = False

    @classmethod
    async def create(cls, factory):
        pending = asyncio.get_running_loop().run_in_executor(None, factory)
        try:
            return cls(await asyncio.shield(pending))
        except asyncio.CancelledError:
            async def reclaim():
                try:
                    resource = await _settle(pending)
                except Exception:
                    return
                await _settle(asyncio.get_running_loop().run_in_executor(_CLOSE_EXECUTOR, _close, resource))
            _defer(reclaim())
            raise

    async def call(self, operation):
        if self.closing:
            raise OSError('Stream resource is closed.')
        if self.pending is not None and not self.pending.done():
            raise RuntimeError('Stream resource already has an operation in flight.')
        self.pending = asyncio.get_running_loop().run_in_executor(None, operation, self.resource)
        return await asyncio.shield(self.pending)

    async def aclose(self):
        if self.closing:
            return
        self.closing = True
        resource, pending = self.resource, self.pending
        self.resource = None

        async def reclaim():
            if pending is not None:
                try:
                    await _settle(pending)
                except Exception:
                    pass
            await _settle(asyncio.get_running_loop().run_in_executor(_CLOSE_EXECUTOR, _close, resource))

        if pending is not None and not pending.done():
            # A Python cancellation cannot abort a kernel read. Keep ownership
            # until it returns; never close/reuse a descriptor underneath it.
            _defer(reclaim())
        else:
            await reclaim()


class FileSource(ThreadResource):
    @classmethod
    async def open(cls, path):
        return await cls.create(lambda: open(path, 'rb', buffering=0))

    async def stat(self):
        return await self.call(lambda file: os.fstat(file.fileno()))

    async def seek(self, position):
        return await self.call(lambda file: file.seek(position))

    async def read(self, size):
        return await self.call(lambda file: file.read(size))