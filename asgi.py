"""
ASGI config for SharewareZ production deployment.
This file wraps the Flask app to be compatible with ASGI servers like uvicorn
and provides async file streaming for downloads.
"""

import asyncio
import contextlib
import os
import re
import json
import uuid
import time
from datetime import datetime, timezone
from asgiref.wsgi import WsgiToAsgi

from sharewarez import create_app, db
from sharewarez.models import DownloadArchive, DownloadRequest, Game, GlobalSettings
from sharewarez.async_streaming import create_async_streaming_response, async_generate_zipstream_response
from sharewarez.utils.security import is_safe_path, get_allowed_base_directories
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.download_limits import (
    acquire_queued_download_slot,
    estimate_path_bytes,
    finish_transfer,
    reserve_transfer,
    run_owned_in_thread,
    throttle_chunks,
    update_transfer_progress,
)
from sharewarez.utils.download_cache import (
    ArchiveCacheError, acquire_archive_lease, resolved_archive_path,
)
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
                await run_owned_in_thread(slot.release, lambda _: None)
                
        except Exception as e:
            # Use print instead of log_system_event to avoid context issues
            print(f"Error in async download handler: {str(e)}")
            
            # Try to send error response, but handle case where response already started
            try:
                await self._send_error(send, 500, "Internal Server Error")
            except Exception as error_e:
                print(f"Could not send error response (response may have already started): {str(error_e)}")
                # Try to close connection gracefully
                try:
                    await send({
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False
                    })
                except Exception:
                    # Connection handling failed, nothing more we can do
                    pass
    
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
                await run_owned_in_thread(slot.release, lambda _: None)
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
                if record.expires_at and record.expires_at <= datetime.now(timezone.utc):
                    record.status = 'expired'
                    db.session.commit()
                    raise DownloadRejected(410, 'Download request expired')
                if record.status != 'available':
                    raise DownloadRejected(400, 'Download not ready')
                data = {'file_path': record.zip_file_path, 'req_id': record.id,
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
                    bandwidth_limit, method=scope.get('method', 'GET'))
            else:
                await self._stream_file(receive, send, data['file_path'], data['filename'],
                    scope, user_id, bandwidth_limit, download_request_id=data['req_id'],
                    archive_id=data['archive_id'], etag=data['etag'], last_modified=data['modified'])
        finally:
            await run_owned_in_thread(lambda: self._release_prepared_download(data), lambda _: None)

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
    ):
        """Run reserve_transfer synchronously inside a Flask app context."""
        with self._flask_app.app_context():
            return reserve_transfer(
                user_id, filename, length,
                download_request_id=download_request_id, game_uuid=game_uuid,
                archive_id=archive_id, range_start=range_start, range_end=range_end,
                http_status=http_status,
            )

    def _sync_update_transfer_progress(self, transfer_id, bytes_sent):
        """Run update_transfer_progress synchronously inside a Flask app context."""
        with self._flask_app.app_context():
            return update_transfer_progress(transfer_id, bytes_sent)

    def _sync_finish_transfer(self, transfer_id, bytes_sent, status):
        """Run finish_transfer synchronously inside a Flask app context."""
        with self._flask_app.app_context():
            finish_transfer(transfer_id, bytes_sent, status)

    async def _watch_disconnect(self, receive, disconnected):
        while not disconnected.is_set():
            message = await receive()
            if message.get('type') == 'http.disconnect':
                disconnected.set()
                return

    async def _stream_file(
        self, receive, send, file_path, filename, scope, user_id=None,
        bandwidth_limit=0, download_request_id=None, game_uuid=None,
        archive_id=None, etag=None, last_modified=None,
    ):
        """Stream a file asynchronously"""
        transfer_id = None
        bytes_sent = 0
        completed = False
        response_started = False
        externally_stopped = False
        disconnected = asyncio.Event()
        disconnect_task = asyncio.create_task(self._watch_disconnect(receive, disconnected))
        try:
            stat = await asyncio.to_thread(os.stat, file_path)
            file_size = stat.st_size
            request_headers = dict(scope.get("headers", []))
            range_header = request_headers.get(b"range", b"").decode("ascii", "ignore")
            etag = etag or f'"{file_size:x}-{stat.st_mtime_ns:x}"'
            modified_dt = last_modified or datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            modified_http = modified_dt.strftime('%a, %d %b %Y %H:%M:%S GMT')
            if_range = request_headers.get(b"if-range", b"").decode("ascii", "ignore").strip()
            if range_header and if_range and if_range not in {etag, modified_http}:
                range_header = ''
            try:
                byte_range = parse_single_byte_range(range_header, file_size)
            except ValueError:
                await self._send_error(
                    send,
                    416,
                    "Requested range is not satisfiable",
                    extra_headers=[(b"content-range", f"bytes */{file_size}".encode())],
                )
                return

            status = 200
            start = 0
            length = file_size
            if byte_range:
                start, end = byte_range
                length = end - start + 1
                status = 206
            if user_id is not None and scope.get('method') != 'HEAD':
                transfer_id, _used_bytes, _quota_bytes = await run_owned_in_thread(
                    lambda: self._sync_reserve_transfer(user_id, filename, length,
                        download_request_id, game_uuid, archive_id, start, (start + length - 1), status),
                    self._cleanup_reservation,
                )
                if transfer_id is None:
                    await self._send_error(
                        send, 429, "Monthly download quota exceeded",
                        extra_headers=[(b"retry-after", b"3600")],
                    )
                    return
            async_generator, headers = await create_async_streaming_response(
                file_path, filename, start=start, length=length
            )
            if byte_range:
                headers["content-range"] = f"bytes {start}-{end}/{file_size}"
            headers['etag'] = etag
            headers['last-modified'] = modified_http
            
            # Send HTTP response start
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()]
            })
            response_started = True
            if scope.get('method') == 'HEAD':
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                completed = True
                return
            
            # Stream file chunks
            progress_updated_at = time.monotonic()
            async for chunk in throttle_chunks(async_generator, bandwidth_limit):
                if disconnected.is_set():
                    break
                if transfer_id is not None and time.monotonic() - progress_updated_at >= 1:
                    still_active = await asyncio.to_thread(
                        self._sync_update_transfer_progress, transfer_id, bytes_sent
                    )
                    if not still_active:
                        externally_stopped = True
                        break
                    progress_updated_at = time.monotonic()
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True
                })
                bytes_sent += len(chunk)
            if disconnected.is_set() or externally_stopped:
                return
            
            # End response
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False
            })
            completed = True
            
        except Exception as e:
            print(f"Error streaming file: {type(e).__name__}")
            if not response_started:
                await self._send_error(send, 500, "Error streaming file")
        finally:
            disconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await disconnect_task
            if transfer_id is not None:
                await asyncio.to_thread(
                    self._sync_finish_transfer, transfer_id, bytes_sent,
                    'completed' if completed else 'interrupted',
                )
    
    async def _handle_streaming_download(
        self, receive, send, download_request_id, file_location, game_name,
        source_path, user_id, bandwidth_limit=0, method='GET',
    ):
        """Handle zipstream downloads for multi-file games"""
        transfer_id = None
        bytes_sent = 0
        completed = False
        response_started = False
        externally_stopped = False
        disconnected = asyncio.Event()
        disconnect_task = asyncio.create_task(self._watch_disconnect(receive, disconnected))
        try:
            # Validate source path is within allowed directories
            allowed_bases = get_allowed_base_directories(self._flask_app)
            if not allowed_bases:
                await self._send_error(send, 500, "Server configuration error")
                return
                
            is_safe, error_message = is_safe_path(source_path, allowed_bases)
            if not is_safe:
                # Use print instead of log_system_event to avoid context issues
                print(f"Security violation - streaming source outside allowed directories: {source_path[:100]}")
                await self._send_error(send, 403, "Access denied")
                return
            
            if not os.path.exists(source_path):
                await self._send_error(send, 404, "Source path not found")
                return
            
            # Get configuration parameters
            chunk_size = self._flask_app.config.get('ZIPSTREAM_CHUNK_SIZE', 65536) if self._flask_app else 65536
            compression_level = self._flask_app.config.get('ZIPSTREAM_COMPRESSION_LEVEL', 0) if self._flask_app else 0
            enable_zip64 = self._flask_app.config.get('ZIPSTREAM_ENABLE_ZIP64', True) if self._flask_app else True
            
            # Generate filename from the original file/folder name
            if file_location:
                base_name = os.path.basename(file_location)
                filename = f"{base_name}.zip" if not base_name.lower().endswith('.zip') else base_name
            else:
                filename = f"{game_name}.zip" if game_name else "download.zip"

            if method == 'HEAD':
                _generator, headers = async_generate_zipstream_response(
                    source_path, filename, chunk_size, compression_level, enable_zip64
                )
                await send({
                    "type": "http.response.start", "status": 200,
                    "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
                })
                response_started = True
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                completed = True
                return

            expected_bytes = await asyncio.to_thread(estimate_path_bytes, source_path)
            transfer_id, _used_bytes, _quota_bytes = await run_owned_in_thread(
                lambda: self._sync_reserve_transfer(user_id, filename, expected_bytes, download_request_id, None),
                self._cleanup_reservation,
            )
            if transfer_id is None:
                await self._send_error(
                    send, 429, "Monthly download quota exceeded",
                    extra_headers=[(b"retry-after", b"3600")],
                )
                return
            
            print(f"Starting zipstream download: {filename}")
            
            # Create zipstream response
            async_generator, headers = async_generate_zipstream_response(
                source_path, filename, chunk_size, compression_level, enable_zip64
            )
            
            # Send HTTP response start
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()]
            })
            response_started = True
            
            # Stream ZIP chunks
            progress_updated_at = time.monotonic()
            async for chunk in throttle_chunks(async_generator, bandwidth_limit):
                if disconnected.is_set():
                    break
                if transfer_id is not None and time.monotonic() - progress_updated_at >= 1:
                    still_active = await asyncio.to_thread(
                        self._sync_update_transfer_progress, transfer_id, bytes_sent
                    )
                    if not still_active:
                        externally_stopped = True
                        break
                    progress_updated_at = time.monotonic()
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True
                })
                bytes_sent += len(chunk)
            if disconnected.is_set() or externally_stopped:
                return
            
            # End response
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False
            })
            
            print(f"Completed zipstream download: {filename}")
            completed = True
            
        except Exception as e:
            # Use print and handle potential undefined filename
            error_filename = locals().get('filename', 'unknown')
            print(f"Error streaming ZIP {error_filename}: {str(e)}")
            
            if not response_started:
                await self._send_error(send, 500, "Error streaming ZIP file")
        finally:
            disconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await disconnect_task
            if transfer_id is not None:
                await asyncio.to_thread(
                    self._sync_finish_transfer, transfer_id, bytes_sent,
                    'completed' if completed else 'interrupted',
                )
    
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
