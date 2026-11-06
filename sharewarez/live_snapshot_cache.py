"""Short-lived, bounded sharing of identical authorized snapshot data."""

from collections import OrderedDict
import threading
import time


_generation = 0
_generation_lock = threading.Lock()


def invalidate_snapshots():
    """Invalidate process snapshots after local commits or PostgreSQL signals."""
    global _generation
    with _generation_lock:
        _generation += 1


class SnapshotCache:
    def __init__(self, ttl=0.8, capacity=32, clock=time.monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, loader):
        # Only data queries are shared: callers MUST authenticate before entering.
        # Serialize misses to avoid one query burst per connected browser. This
        # runs in the background executor, never on the ASGI event loop.
        with self._lock:
            key = (_generation, key)
            now = self.clock()
            cached = self._entries.get(key)
            if cached is not None and now - cached[0] < self.ttl:
                self._entries.move_to_end(key)
                return cached[1]
            value = loader()
            self._entries[key] = (self.clock(), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
            return value
