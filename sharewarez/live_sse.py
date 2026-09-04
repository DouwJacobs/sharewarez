"""ASGI SSE boundary. Blocking database operations never run on the event loop."""

import asyncio
import contextlib
import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine import make_url
from werkzeug.sansio.utils import host_is_trusted

from sharewarez.live_events import ConnectionLimitError, LiveEventHub, PostgresEventListener
from sharewarez.live_snapshots import LiveAccessDenied, snapshot
from sharewarez.live_snapshot_cache import SnapshotCache
from sharewarez.security import security_headers
from sharewarez.observability import normalize_request_id


class DownloadEventStream:
    def __init__(self, app, *, snapshotter=snapshot, interval=1.0, heartbeat=15.0, send_timeout=10.0):
        self.app = app
        self.cache = SnapshotCache()
        self.snapshotter = (lambda *args: snapshot(*args, cache=self.cache)) if snapshotter is snapshot else snapshotter
        self.interval = interval
        self.heartbeat = heartbeat
        self.send_timeout = send_timeout
        self.hub = LiveEventHub()
        self._initializing = 0
        self._closing = False
        url = make_url(app.config["SQLALCHEMY_DATABASE_URI"]).set(drivername="postgresql")
        self.listener = PostgresEventListener(url.render_as_string(hide_password=False), self.hub)

    async def close(self):
        self._closing = True
        self.hub.signal()
        await asyncio.to_thread(self.listener.stop)

    async def _send(self, send, message):
        await asyncio.wait_for(send(message), self.send_timeout)

    async def __call__(self, scope, receive, send):
        started = time.perf_counter()
        request_id = normalize_request_id(dict(scope.get('headers', [])).get(b'x-request-id', b'').decode('latin1'))
        response_status = 500
        async def traced_send(message):
            nonlocal response_status
            if message['type'] == 'http.response.start':
                response_status = message['status']
                headers = dict(message.get('headers', []))
                for name, value in security_headers(self.app, secure=scope.get('scheme') == 'https').items():
                    headers.setdefault(name.lower().encode(), value.encode())
                headers[b'x-request-id'] = request_id.encode()
                headers[b'server-timing'] = f'app;dur={(time.perf_counter() - started) * 1000:.2f}'.encode()
                message = {**message, 'headers': list(headers.items())}
            await send(message)
        try:
            await self._serve(scope, receive, traced_send)
        finally:
            logging.getLogger('gamelibrary.request').info('live stream closed', extra={
                'request_id': request_id, 'method': scope['method'], 'path': '/api/live/downloads',
                'status': response_status, 'duration_ms': round((time.perf_counter() - started) * 1000, 2),
            })

    async def _serve(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin1")
        origin = headers.get(b"origin", b"").decode("latin1")
        trusted = self.app.config.get("TRUSTED_HOSTS")
        status = None
        if scope["method"] != "GET":
            status = 405
        elif (trusted and not host_is_trusted(host, trusted)) or headers.get(b"sec-fetch-site") == b"cross-site":
            status = 403
        elif origin:
            try:
                parsed_origin = urlsplit(origin)
                if parsed_origin.netloc != host or parsed_origin.scheme not in {"http", "https"}:
                    status = 403
            except ValueError:
                status = 403
        try:
            if len(scope.get("query_string", b"")) > 4096:
                raise ValueError()
            query = parse_qs(scope.get("query_string", b"").decode("ascii"), max_num_fields=4)
            view = query.get("view", ["downloads"])[0]
            ids = tuple(set(filter(None, query.get("ids", [""])[0].split(","))))
            if view not in {"downloads", "activity", "cache"} or len(ids) > 100 or any(len(item) > 36 for item in ids):
                raise ValueError()
            if view == "downloads":
                ids = tuple(int(item) for item in ids)
                if any(item <= 0 for item in ids):
                    raise ValueError()
        except (ValueError, UnicodeError):
            status = status or 400
        if status:
            await self._error(send, status)
            return
        # Admission preparation itself must be bounded, before launching DB work.
        if self._closing or self._initializing >= 16:
            await self._error(send, 429)
            return
        self._initializing += 1
        try:
            initial = await asyncio.to_thread(self.snapshotter, self.app, scope, view, ids)
        except LiveAccessDenied as error:
            await self._error(send, error.status)
            return
        except Exception:
            self.app.logger.warning("Live download snapshot unavailable")
            await self._error(send, 503)
            return
        finally:
            self._initializing -= 1
        topics = {"transfers", "downloads", "archives"} if view == "downloads" else (
            {"transfers"} if view == "activity" else {"archives", "transfers"}
        )
        try:
            subscription = self.hub.subscribe(initial["user_id"], topics)
        except ConnectionLimitError:
            await self._error(send, 429)
            return
        self.listener.start()
        async def disconnected():
            while True:
                if (await receive())["type"] == "http.disconnect":
                    return
        disconnect = asyncio.create_task(disconnected())
        try:
            await self._send(send, {"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"text/event-stream; charset=utf-8"),
                (b"cache-control", b"no-store"), (b"x-accel-buffering", b"no"),
                (b"x-content-type-options", b"nosniff"),
            ]})
            data = initial
            while not disconnect.done() and not self._closing:
                await self._send(send, {"type": "http.response.body", "more_body": True,
                    "body": b"retry: 3000\nevent: snapshot\ndata: " + json.dumps(data, separators=(",", ":")).encode() + b"\n\n"})
                # Clear before fetching the NEXT snapshot, not afterwards: changes
                # during the query must remain dirty for a subsequent refresh.
                await asyncio.wait({disconnect}, timeout=self.interval)
                if disconnect.done() or self._closing:
                    break
                changed = asyncio.create_task(subscription.changed.wait())
                try:
                    await asyncio.wait({changed, disconnect}, timeout=self.heartbeat, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    changed.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await changed
                if disconnect.done() or self._closing:
                    break
                subscription.changed.clear()
                # Timed snapshots act as heartbeats, reauthorize, and recover lost signals.
                data = await asyncio.to_thread(self.snapshotter, self.app, scope, view, ids)
            if not disconnect.done():
                await self._send(send, {"type": "http.response.body", "body": b"", "more_body": False})
        except LiveAccessDenied:
            await self._send(send, {"type": "http.response.body", "body": b"event: access-revoked\ndata: {}\n\n", "more_body": False})
        except (TimeoutError, ConnectionError):
            pass
        except Exception:
            # Close the stream so EventSource can reconnect or switch to polling.
            # Avoid exception details containing query values or connection data.
            self.app.logger.warning("Live download stream interrupted")
        finally:
            disconnect.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await disconnect
            self.hub.unsubscribe(subscription)

    async def _error(self, send, status):
        await self._send(send, {"type": "http.response.start", "status": status,
            "headers": [(b"cache-control", b"no-store"), (b"content-type", b"application/json")]})
        await self._send(send, {"type": "http.response.body", "body": b'{"error":"Live updates unavailable"}'})
