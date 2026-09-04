"""Bounded change signals for live downloads; PostgreSQL remains authoritative.

One LISTEN connection per web process, never per browser. Notifications contain
only topic names, not user data. Consumers must authorize and fetch snapshots.
"""

import asyncio
from collections import Counter, deque
from dataclasses import dataclass, field
import logging
import select
import threading

import psycopg2


CHANNEL = "sharewarez_download_events"
TOPICS = frozenset({"transfers", "downloads", "archives"})
logger = logging.getLogger(__name__)


class ConnectionLimitError(Exception):
    pass


@dataclass(eq=False)
class Subscription:
    user_id: int
    topics: frozenset
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class LiveEventHub:
    """Loop-owned subscriptions with a single conflated thread-to-loop wakeup."""

    def __init__(self, *, max_connections=100, per_user=4):
        self.max_connections = max_connections
        self.per_user = per_user
        self._subscriptions = set()
        self._users = Counter()
        self._lock = threading.Lock()
        self._pending = set()
        self._scheduled = False
        self._loop = None

    def subscribe(self, user_id, topics):
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("LiveEventHub must be used on one event loop")
        self._loop = loop
        topics = frozenset(topics)
        if not topics or not topics <= TOPICS:
            raise ValueError("Unknown live event topic")
        if len(self._subscriptions) >= self.max_connections or self._users[user_id] >= self.per_user:
            raise ConnectionLimitError()
        subscription = Subscription(user_id, topics)
        subscription.changed.set()  # Every connection/reconnection gets a fresh snapshot.
        self._subscriptions.add(subscription)
        self._users[user_id] += 1
        return subscription

    def unsubscribe(self, subscription):
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)
            self._users[subscription.user_id] -= 1
            if not self._users[subscription.user_id]:
                del self._users[subscription.user_id]

    def signal(self, topics=TOPICS):
        """Thread-safe; bursts retain at most three topics and one callback."""
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                return
            self._pending.update(TOPICS.intersection(topics))
            if self._scheduled or not self._pending:
                return
            self._scheduled = True
            try:
                self._loop.call_soon_threadsafe(self._deliver)
            except RuntimeError:  # Event loop shut down concurrently.
                self._scheduled = False
                self._pending.clear()

    def _deliver(self):
        with self._lock:
            topics = self._pending
            self._pending = set()
            self._scheduled = False
        for subscription in self._subscriptions:
            if subscription.topics.intersection(topics):
                subscription.changed.set()


class PostgresEventListener:
    """Dedicated autocommit listener with reconnect/resync and bounded memory."""

    def __init__(self, dsn, hub, *, retry_seconds=2):
        self._dsn = dsn
        self._hub = hub
        self._retry_seconds = retry_seconds
        self._stop = threading.Event()
        self._thread = None
        self.ready = threading.Event()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="download-events", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6)

    def _run(self):
        while not self._stop.is_set():
            connection = None
            try:
                connection = psycopg2.connect(self._dsn, connect_timeout=5, application_name="sharewarez-live")
                connection.autocommit = True
                # Lost individual hints are harmless: every wake reads current DB state.
                connection.notifies = deque(maxlen=32)
                with connection.cursor() as cursor:
                    cursor.execute(f"LISTEN {CHANNEL}")
                self.ready.set()
                self._hub.signal()
                while not self._stop.is_set():
                    if not select.select([connection], [], [], 0.5)[0]:
                        continue
                    connection.poll()
                    # A full ring may have discarded an earlier, different topic.
                    topics = set(TOPICS) if len(connection.notifies) == 32 else set()
                    while connection.notifies:
                        topic = connection.notifies.popleft().payload
                        if topic in TOPICS:
                            topics.add(topic)
                    self._hub.signal(topics)
            except (psycopg2.Error, OSError, ValueError):
                # Never include connection exceptions: they can expose credentials.
                logger.warning("Live download listener disconnected; retrying")
            finally:
                self.ready.clear()
                if connection is not None:
                    connection.close()
            self._stop.wait(self._retry_seconds)
