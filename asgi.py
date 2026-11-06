"""
ASGI config for GameLibrary production deployment.
This file wraps the Flask app to be compatible with ASGI servers like uvicorn
and provides async file streaming for downloads.
"""

import asyncio
import contextlib
import os
import re
import json
import logging
import uuid
from datetime import datetime, timezone
from asgiref.wsgi import WsgiToAsgi

from sharewarez import create_app, db
from sharewarez.models import DownloadArchive, DownloadRequest, Game, GlobalSettings
from sharewarez.async_streaming import create_async_streaming_response, async_generate_zipstream_response
from sharewarez.utils.security import is_safe_path, get_allowed_base_directories
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.download_limits import (
    acquire_queued_download_slot,
    heartbeat_transfer,
    DownloadAdmissionRejected,
    finish_transfer,
    reserve_transfer,
    run_owned_in_thread,
    update_transfer_progress,
)
from sharewarez.utils.download_cache import (
    ArchiveCacheError, acquire_archive_lease, resolved_archive_path,
)
from sharewarez.observability import normalize_request_id
from sharewarez.utils.stream_control import BOOKKEEPING_EXECUTOR, TransferControl, finish_cleanup
from sharewarez.utils.stream_io import FileSource
from sharewarez.utils.download_sources import source_entries
from sharewarez.utils.transfer_evidence import TransferFailure, observed_chunks, observed_send
from sqlalchemy import select
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


class DownloadRejected(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def parse_single_byte_range(range_header, file_size):
    """Return an inclusive (start, end) tuple for one valid HTTP byte range."""
    if not range_header:
        return None
    if file_size <= 0 or not range_header.startswith("bytes="):
        raise ValueError("Invalid byte range")

    value = range_header[6:].strip()
    if not value or "," in value or "-" not in value:
        raise ValueError("Only one byte range is supported")

    start_text, end_text = value.split("-", 1)
    try:
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(0, file_size - suffix_length)
            end = file_size - 1
        else:
            start = int(start_text)
            end = file_size - 1 if not end_text else int(end_text)
            if start < 0 or end < start or start >= file_size:
                raise ValueError
            end = min(end, file_size - 1)
    except (TypeError, ValueError):
        raise ValueError("Invalid byte range") from None

    return start, end


# Proper ASGI application with lifespan protocol support
class LazyASGIApp:
    def __init__(self):
        self._app = None
        self._flask_app = None
        self._download_events = None
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            # Handle ASGI lifespan protocol
            await self._handle_lifespan(receive, send)
        elif scope["type"] == "http":
            # Handle HTTP requests - check for download routes first
            path = scope["path"]
            if path == '/api/live/downloads':
                if self._flask_app is None:
                    self._flask_app = create_app()
                if self._download_events is None:
                    from sharewarez.live_sse import DownloadEventStream
                    self._download_events = DownloadEventStream(self._flask_app)
                await self._download_events(scope, receive, send)
                return
            
            # Check if this is a download route
            if (path.startswith('/download_zip/') or 
                path.startswith('/api/downloadrom/')):
                await self._handle_download(scope, receive, send)
                return
            
            # For all other routes, use Flask
            if self._app is None:
                # Create Flask app only on first HTTP request, not during module import
                # Database initialization is handled by InitializationManager before workers start
                if self._flask_app is None:
                    self._flask_app = create_app()

                # Wrap with ASGI adapter
                self._app = WsgiToAsgi(self._flask_app)
            
            await self._app(scope, receive, send)
    
    async def _handle_download(self, scope, receive, send):
        """Handle download routes with async file streaming"""
        scope = dict(scope)
        supplied = dict(scope.get('headers', [])).get(b'x-request-id', b'').decode('ascii', 'ignore')
        scope['correlation_id'] = normalize_request_id(supplied)
        raw_send = send
        response_started = False
        async def send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
                message = {**message, 'headers': [*message.get('headers', []),
                           (b'x-request-id', scope['correlation_id'].encode('ascii'))]}
                if message['status'] >= 400:
                    route = '/download_zip/<download_id>' if scope['path'].startswith('/download_zip/') else '/api/downloadrom/<game_uuid>'
                    logging.getLogger('gamelibrary.download').warning('Download rejected', extra={
                        'request_id': scope['correlation_id'], 'path': route,
                        'method': scope['method'], 'status': message['status']})
            await raw_send(message)
        path = scope["path"]
        method = scope["method"]
        
        # Download managers commonly probe with HEAD before issuing a ranged GET.
        if method not in {"GET", "HEAD"}:
            await self._send_error(send, 405, "Method Not Allowed")
            return
        
        try:
            # Initialize Flask app if needed for database access
            if self._flask_app is None:
                # Database initialization is handled by InitializationManager
                self._flask_app = create_app()
            
            user_id = await self._get_user_from_session(scope)
            if not user_id:
                await self._send_error(send, 401, "Unauthorized")
                return

            engine, concurrent_limit, bandwidth_limit, queue_wait, queue_request_id, queue_priority = await asyncio.to_thread(
                self._sync_download_settings, path, user_id
            )
            if method == 'HEAD':
                if path.startswith('/download_zip/'):
                    await self._handle_zip_download(scope, receive, send, path, user_id, bandwidth_limit)
                elif path.startswith('/api/downloadrom/'):
                    await self._handle_rom_download(scope, receive, send, path, user_id, bandwidth_limit)
                return
            connected, slot = await self._admit_connected(receive,
                engine,
                user_id,
                concurrent_limit,
                request_id=queue_request_id,
                priority=queue_priority,
                wait_seconds=queue_wait,
            )
            if not connected:
                return
            if slot is None:
                await self._send_error(
                    send, 429, "Download queue wait expired",
                    extra_headers=[(b"retry-after", b"2")],
                )
                return

            try:
                if path.startswith('/download_zip/'):
                    await self._handle_zip_download(scope, receive, send, path, user_id, bandwidth_limit)
                elif path.startswith('/api/downloadrom/'):
                    await self._handle_rom_download(scope, receive, send, path, user_id, bandwidth_limit)
            finally:
                await run_owned_in_thread(slot.release, lambda _: None, executor=BOOKKEEPING_EXECUTOR)
                
        except Exception as exc:
            logging.getLogger('gamelibrary.download').error('Download handler failed: %s', type(exc).__name__, extra={'request_id': scope['correlation_id']})
            if response_started:
                # Let the ASGI server terminate an incomplete representation;
                # never invent a second status or a successful end-of-body.
                raise
            with contextlib.suppress(Exception):
                await self._send_error(send, 500, 'Internal Server Error')

    async def _admit_connected(self, receive, *args, **kwargs):
        disconnected = asyncio.Event()
        watcher = asyncio.create_task(self._watch_disconnect(receive, disconnected))
        admission = asyncio.create_task(acquire_queued_download_slot(*args, **kwargs))
        async def abandon():
            admission.cancel()
            try:
                slot = await admission
            except asyncio.CancelledError:
                return
            if slot is not None:
                await run_owned_in_thread(slot.release, lambda _: None, executor=BOOKKEEPING_EXECUTOR)
        try:
            await asyncio.wait((watcher, admission), return_when=asyncio.FIRST_COMPLETED)
            if watcher.done():
                await watcher
            if disconnected.is_set():
                await abandon()
                return False, None
            return True, await admission
        except BaseException:
            await abandon()
            raise
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    def _sync_download_settings(self, path, user_id):
        with self._flask_app.app_context():
            record = db.session.execute(select(GlobalSettings)).scalars().first()
            settings = dict(record.settings or {}) if record else {}
            concurrent_limit = max(1, min(int(settings.get('maxConcurrentDownloadsPerUser', 2)), 20))
            bandwidth_limit = max(0.0, min(float(settings.get('downloadBandwidthLimitMbps', 0)), 10000.0))
            queue_wait = max(0, min(int(settings.get('downloadQueueWaitSeconds', 10)), 60))
            queue_request_id = None
            queue_priority = 0
            if path.startswith('/download_zip/'):
                match = re.match(r'/download_zip/(\d+)', path)
                if match:
                    queue_request_id = int(match.group(1))
                    queued_request = db.session.execute(
                        select(DownloadRequest).where(
                            DownloadRequest.id == queue_request_id,
                            DownloadRequest.user_id == user_id,
                        )
                    ).scalar_one_or_none()
                    if queued_request is not None:
                        queue_priority = queued_request.priority
                    else:
                        queue_request_id = None
            engine = db.engine
            return engine, concurrent_limit, bandwidth_limit, queue_wait, queue_request_id, queue_priority

    def _sync_prepare_zip(self, download_id, user_id):
        lease = None
        try:
            with self._flask_app.app_context():
                record = db.session.scalar(select(DownloadRequest).where(
                    DownloadRequest.id == download_id, DownloadRequest.user_id == user_id))
                if record is None:
                    raise DownloadRejected(404, 'Download not found')
                from sharewarez.utils.download_state import delivery_path, download_state
                state = download_state(record, active=None, latest=None)
                if 'download' not in state['allowed_actions']:
                    raise DownloadRejected(410 if state['status'] == 'expired' else 409, state['message'] or 'Download not ready')
                data = {'file_path': delivery_path(record), 'req_id': record.id,
                        'file_location': record.file_location,
                        'game_name': record.game.name if record.game else None,
                        'archive_id': record.archive_id, 'etag': None,
                        'modified': None, 'filename': None, 'lease': None}
                if record.archive_id:
                    try:
                        lease = acquire_archive_lease(record.archive_id)
                    except PoolTimeoutError as exc:
                        raise DownloadRejected(503, 'Download capacity is busy; retry shortly') from exc
                    if lease is None:
                        raise DownloadRejected(409, 'Cached download is being maintained')
                    archive = db.session.get(DownloadArchive, record.archive_id)
                    if archive is None or archive.state != 'ready':
                        raise DownloadRejected(409, 'Resumable download is still being prepared')
                    try:
                        data['file_path'] = str(resolved_archive_path(archive))
                    except ArchiveCacheError:
                        archive.state = 'failed'
                        archive.failure_code = 'archive_missing'
                        archive.failure_message = 'The cached file is missing and must be rebuilt.'
                        record.status = 'failed'
                        db.session.commit()
                        raise DownloadRejected(500, 'Cached download is unavailable') from None
                    archive.last_accessed_at = datetime.now(timezone.utc)
                    db.session.commit()
                    data.update(etag=f'"{archive.sha256}"', modified=archive.ready_at,
                                filename=archive.display_name, lease=lease)
                path = data['file_path']
                if not path:
                    raise DownloadRejected(404, 'File not found')
                if not data['archive_id']:
                    bases = get_allowed_base_directories(self._flask_app)
                    if not bases:
                        raise DownloadRejected(500, 'Server configuration error')
                    if not is_safe_path(path, bases)[0]:
                        raise DownloadRejected(403, 'Access denied')
                if not os.path.exists(path):
                    raise DownloadRejected(404, 'File not found')
                data['is_dir'] = os.path.isdir(path)
                data['filename'] = data['filename'] or os.path.basename(path)
                return data
        except BaseException:
            if lease is not None:
                lease.release()
            raise

    @staticmethod
    def _release_prepared_download(data):
        if data and data.get('lease') is not None:
            data['lease'].release()

    async def _handle_zip_download(self, scope, receive, send, path, user_id, bandwidth_limit):
        match = re.fullmatch(r'/download_zip/(\d+)', path)
        if not match:
            await self._send_error(send, 400, 'Invalid download ID')
            return
        try:
            data = await run_owned_in_thread(
                lambda: self._sync_prepare_zip(int(match.group(1)), user_id),
                self._release_prepared_download,
            )
        except DownloadRejected as error:
            await self._send_error(send, error.status, str(error))
            return
        try:
            if data['is_dir']:
                await self._handle_streaming_download(receive, send, data['req_id'],
                    data['file_location'], data['game_name'], data['file_path'], user_id,
                    bandwidth_limit, method=scope.get('method', 'GET'), correlation_id=scope.get('correlation_id'))
            else:
                await self._stream_file(receive, send, data['file_path'], data['filename'],
                    scope, user_id, bandwidth_limit, download_request_id=data['req_id'],
                    archive_id=data['archive_id'], etag=data['etag'], last_modified=data['modified'])
        finally:
            await run_owned_in_thread(lambda: self._release_prepared_download(data), lambda _: None, executor=BOOKKEEPING_EXECUTOR)

    def _sync_prepare_rom(self, game_uuid):
        with self._flask_app.app_context():
            game = db.session.scalar(select(Game).where(Game.uuid == game_uuid))
            if game is None:
                raise DownloadRejected(404, 'Game not found')
            path = game.full_disk_path
            if not path or not os.path.exists(path):
                raise DownloadRejected(404, 'ROM file not found on disk')
            if not is_safe_path(path, get_allowed_base_directories(self._flask_app))[0]:
                raise DownloadRejected(403, 'Access denied')
            if os.path.isdir(path):
                raise DownloadRejected(400, 'This game is a folder and cannot be played directly')
            return path, os.path.basename(path), game.uuid

    async def _handle_rom_download(self, scope, receive, send, path, user_id, bandwidth_limit):
        try:
            game_uuid = str(uuid.UUID(path.removeprefix('/api/downloadrom/')))
        except ValueError:
            await self._send_error(send, 400, 'Invalid game identifier')
            return
        try:
            file_path, filename, game_uuid = await asyncio.to_thread(self._sync_prepare_rom, game_uuid)
        except DownloadRejected as error:
            await self._send_error(send, error.status, str(error))
            return
        await self._stream_file(receive, send, file_path, filename, scope, user_id,
                                bandwidth_limit, game_uuid=game_uuid)

    async def _get_user_from_session(self, scope):
        """Validate the current account off the event loop, as SSE does."""
        from sharewarez.live_snapshots import authenticate, LiveAccessDenied

        def resolve():
            with self._flask_app.app_context():
                try:
                    return authenticate(self._flask_app, scope, 'downloads').id
                except LiveAccessDenied:
                    return None
        return await asyncio.to_thread(resolve)

    def _cleanup_reservation(self, result):
        if result[0] is not None:
            self._sync_finish_transfer(result[0], 0, 'interrupted')

    def _sync_reserve_transfer(
        self, user_id, filename, length, download_request_id, game_uuid=None,
        archive_id=None, range_start=None, range_end=None, http_status=None,
        delivery_kind=None, expected_response_bytes=None, correlation_id=None, source_path=None,
    ):
        """Run reserve_transfer synchronously inside a Flask app context."""
        with self._flask_app.app_context():
            return reserve_transfer(
                user_id, filename, length,
                download_request_id=download_request_id, game_uuid=game_uuid,
                archive_id=archive_id, range_start=range_start, range_end=range_end,
                http_status=http_status, delivery_kind=delivery_kind,
                expected_response_bytes=expected_response_bytes, correlation_id=correlation_id, source_path=source_path,
            )

    def _sync_update_transfer_progress(self, transfer_id, bytes_sent):
        """Run update_transfer_progress synchronously inside a Flask app context."""
        try:
            with self._flask_app.app_context():
                return update_transfer_progress(transfer_id, bytes_sent)
        except Exception as exc:
            raise TransferFailure('progress_store_error') from exc

    def _sync_finish_transfer(self, transfer_id, bytes_sent, status, end_reason=None):
        """Run finish_transfer synchronously inside a Flask app context."""
        with self._flask_app.app_context():
            finish_transfer(transfer_id, bytes_sent, status, end_reason=end_reason)

    async def _watch_disconnect(self, receive, disconnected):
        while not disconnected.is_set():
            message = await receive()
            if message.get('type') == 'http.disconnect':
                disconnected.set()
                return

    def _sync_owner_heartbeat(self, transfer_id):
        assert self._flask_app is not None
        with self._flask_app.app_context():
            return heartbeat_transfer(transfer_id)

    async def _finish_delivery(self, control, source, transfer_id, state, completed, end_reason):
        try:
            await control.close()
        finally:
            try:
                if source is not None:
                    await source.aclose()
            finally:
                if transfer_id is not None:
                    await run_owned_in_thread(lambda: self._sync_finish_transfer(transfer_id, state[0],
                        'completed' if completed else 'interrupted',
                        'completed' if completed else (control.reason if control.stopped.is_set() else end_reason)), lambda _: None, executor=BOOKKEEPING_EXECUTOR)

    async def _deliver_body(self, generator, control, send, bandwidth_limit, state, *, archive=False, expected=None):
        chunks = observed_chunks(generator, archive=archive)
        try:
            while True:
                try:
                    chunk = await control.wait(anext(chunks))
                except StopAsyncIteration:
                    break
                control.check()
                if not chunk:
                    continue
                if expected is not None and state[0] + len(chunk) > expected:
                    raise TransferFailure('source_read_error')
                await control.pace(len(chunk), bandwidth_limit)
                await control.wait(observed_send(send, {'type': 'http.response.body', 'body': chunk, 'more_body': True}))
                state[0] += len(chunk)
                await control.progress(state[0])
            control.check()
            if expected is not None and state[0] != expected:
                raise TransferFailure('source_read_error')
            await control.wait(observed_send(send, {'type': 'http.response.body', 'body': b'', 'more_body': False}))
        finally:
            await chunks.aclose()

    async def _stream_file(
        self, receive, send, file_path, filename, scope, user_id=None,
        bandwidth_limit=0, download_request_id=None, game_uuid=None,
        archive_id=None, etag=None, last_modified=None,
    ):
        transfer_id, source = None, None
        state, completed, response_started = [0], False, False
        end_reason = 'unknown'
        correlation_id = normalize_request_id(scope.get('correlation_id', ''))
        control = TransferControl(receive, self._sync_owner_heartbeat, self._sync_update_transfer_progress)
        async def send_response(message):
            await control.wait(observed_send(send, message))
        try:
            source = await control.wait(FileSource.open(file_path))
            stat = await control.wait(source.stat())
            file_size = stat.st_size
            request_headers = dict(scope.get('headers', []))
            range_header = request_headers.get(b'range', b'').decode('ascii', 'ignore')
            etag = etag or f'"{file_size:x}-{stat.st_mtime_ns:x}"'
            modified_dt = last_modified or datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            modified_http = modified_dt.strftime('%a, %d %b %Y %H:%M:%S GMT')
            if_range = request_headers.get(b'if-range', b'').decode('ascii', 'ignore').strip()
            if range_header and if_range and if_range not in {etag, modified_http}:
                range_header = ''
            try:
                byte_range = parse_single_byte_range(range_header, file_size)
            except ValueError:
                await self._send_error(send_response, 416, 'Requested range is not satisfiable',
                    extra_headers=[(b'content-range', f'bytes */{file_size}'.encode())])
                return
            status, start, length = 200, 0, file_size
            if byte_range:
                start, end = byte_range
                length, status = end - start + 1, 206
            if user_id is not None and scope.get('method') != 'HEAD':
                transfer_id, _used, _quota = await control.wait(run_owned_in_thread(
                    lambda: self._sync_reserve_transfer(user_id, filename, length, download_request_id,
                        game_uuid, archive_id, start, start + length - 1, status,
                        'cached_archive' if archive_id else 'direct', length, correlation_id, file_path),
                    self._cleanup_reservation, executor=BOOKKEEPING_EXECUTOR))
                if transfer_id is None:
                    await self._send_error(send_response, 429, 'Monthly download quota exceeded', extra_headers=[(b'retry-after', b'3600')])
                    return
            control.start(transfer_id)
            generator, headers = await control.wait(create_async_streaming_response(
                file_path, filename, start=start, length=length, file_source=source, file_stat=stat))
            if byte_range:
                headers['content-range'] = f'bytes {start}-{end}/{file_size}'
            headers.update(etag=etag, **{'last-modified': modified_http})
            await send_response({'type': 'http.response.start', 'status': status,
                                 'headers': [(key.encode(), value.encode()) for key, value in headers.items()]})
            response_started = True
            if scope.get('method') == 'HEAD':
                await send_response({'type': 'http.response.body', 'body': b'', 'more_body': False})
            else:
                await self._deliver_body(generator, control, send, bandwidth_limit, state, expected=length)
            completed = True
        except Exception as exc:
            end_reason = exc.reason if isinstance(exc, TransferFailure) else 'source_read_error'
            logging.getLogger('gamelibrary.download').error('File transfer failed: %s (%s)', end_reason, type(exc).__name__, extra={'request_id': correlation_id})
            if not response_started and not control.stopped.is_set():
                with contextlib.suppress(TransferFailure):
                    await self._send_error(send_response, 409 if isinstance(exc, DownloadAdmissionRejected) else 500, str(exc) if isinstance(exc, DownloadAdmissionRejected) else 'Error streaming file')
        finally:
            await finish_cleanup(self._finish_delivery(control, source, transfer_id, state, completed, end_reason))

    def _sync_archive_exclusions(self):
        assert self._flask_app is not None
        from sharewarez.utils.download_cache import _excluded_folder_names
        with self._flask_app.app_context():
            return sorted(_excluded_folder_names())

    def _sync_validate_live_source(self, source_path):
        assert self._flask_app is not None
        allowed = get_allowed_base_directories(self._flask_app)
        if not allowed:
            return 500, 'Server configuration error'
        if not is_safe_path(source_path, allowed)[0]:
            return 403, 'Access denied'
        if not os.path.isdir(source_path):
            return 404, 'Source path not found'
        return None

    async def _handle_streaming_download(
        self, receive, send, download_request_id, file_location, game_name,
        source_path, user_id, bandwidth_limit=0, method='GET', correlation_id=None,
    ):
        assert self._flask_app is not None
        correlation_id = normalize_request_id(correlation_id or '')
        transfer_id = None
        state, completed, response_started = [0], False, False
        end_reason = 'unknown'
        control = TransferControl(receive, self._sync_owner_heartbeat, self._sync_update_transfer_progress)
        async def send_response(message):
            await control.wait(observed_send(send, message))
        try:
            rejected = await control.wait(asyncio.to_thread(self._sync_validate_live_source, source_path))
            if rejected:
                await self._send_error(send_response, *rejected)
                return
            config = self._flask_app.config
            chunk_size = config.get('ZIPSTREAM_CHUNK_SIZE', 65536)
            compression = config.get('ZIPSTREAM_COMPRESSION_LEVEL', 0)
            zip64 = config.get('ZIPSTREAM_ENABLE_ZIP64', True)
            exclusions = await control.wait(asyncio.to_thread(self._sync_archive_exclusions))
            base = os.path.basename(file_location) if file_location else (game_name or 'download')
            filename = base if base.lower().endswith('.zip') else f'{base}.zip'
            if method != 'HEAD':
                def estimate():
                    return sum(entry['size'] for entry in source_entries(source_path, exclusions))
                expected = await control.wait(asyncio.to_thread(estimate))
                transfer_id, _used, _quota = await control.wait(run_owned_in_thread(
                    lambda: self._sync_reserve_transfer(user_id, filename, expected, download_request_id,
                        delivery_kind='live_archive', http_status=200, correlation_id=correlation_id, source_path=source_path),
                    self._cleanup_reservation, executor=BOOKKEEPING_EXECUTOR))
                if transfer_id is None:
                    await self._send_error(send_response, 429, 'Monthly download quota exceeded', extra_headers=[(b'retry-after', b'3600')])
                    return
            control.start(transfer_id)
            generator, headers = async_generate_zipstream_response(source_path, filename, chunk_size, compression, zip64, excluded_folders=exclusions)
            await send_response({'type': 'http.response.start', 'status': 200,
                                 'headers': [(key.encode(), value.encode()) for key, value in headers.items()]})
            response_started = True
            if method == 'HEAD':
                await send_response({'type': 'http.response.body', 'body': b'', 'more_body': False})
            else:
                await self._deliver_body(generator, control, send, bandwidth_limit, state, archive=True)
            completed = True
        except Exception as exc:
            end_reason = exc.reason if isinstance(exc, TransferFailure) else 'archive_generation_error'
            logging.getLogger('gamelibrary.download').error('Archive transfer failed: %s (%s)', end_reason, type(exc).__name__, extra={'request_id': correlation_id})
            if not response_started and not control.stopped.is_set():
                with contextlib.suppress(TransferFailure):
                    await self._send_error(send_response, 409 if isinstance(exc, DownloadAdmissionRejected) else 500, str(exc) if isinstance(exc, DownloadAdmissionRejected) else 'Error streaming ZIP file')
        finally:
            await finish_cleanup(self._finish_delivery(control, None, transfer_id, state, completed, end_reason))

    async def _send_error(self, send, status_code, message, extra_headers=None):
        """Send an HTTP error response"""
        response_body = json.dumps({"error": message}).encode()
        
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(response_body)).encode())
        ]
        headers.extend(extra_headers or [])
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": headers
        })
        
        await send({
            "type": "http.response.body",
            "body": response_body,
            "more_body": False
        })
    
    async def _handle_lifespan(self, receive, send):
        """Let Uvicorn own OS signals and honor the complete ASGI lifecycle."""
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    if self._download_events is not None:
                        await self._download_events.close()
                    from sharewarez.utils.shutdown import request_shutdown
                    request_shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception:
                    await send({"type": "lifespan.shutdown.failed", "message": "Shutdown failed"})
                return

# Create lazy ASGI app (won't call create_app() until first HTTP request)
asgi_app = LazyASGIApp()
