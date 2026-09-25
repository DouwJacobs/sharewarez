"""Managed immutable ZIP cache for resumable directory downloads."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import zipfile

from flask import current_app
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from sharewarez import db
from sharewarez.models import DownloadArchive, DownloadRequest, DownloadTransfer, GlobalSettings
from sharewarez.utils.security import get_allowed_base_directories, is_safe_path


ARCHIVE_FORMAT_VERSION = 2
ARCHIVE_STATES = {'queued', 'building', 'ready', 'failed', 'deleting'}
DEFAULT_POLICY = {
    'archiveCacheMode': 'prefer',
    'archiveCacheMaxGb': 100,
    'archiveCacheMinFreeGb': 10,
    'archiveCacheRetentionDays': 7,
    'archiveCacheBuildConcurrency': 1,
    'archiveCacheFallbackEnabled': True,
}


class ArchiveCacheError(RuntimeError):
    def __init__(self, message, code='cache_error'):
        super().__init__(message)
        self.code = code


class _HashingArchiveWriter:
    """Hash the exact ZIP bytes as they are written without a second disk pass."""

    def __init__(self, raw_file):
        self.raw_file = raw_file
        self.digest = hashlib.sha256()
        self.offset = 0

    def write(self, data):
        written = self.raw_file.write(data)
        if written:
            self.digest.update(memoryview(data)[:written])
            self.offset += written
        return written

    def tell(self):
        return self.offset

    def flush(self):
        return self.raw_file.flush()

    def seekable(self):
        return False


def _validate_archive_index(path: Path, expected_entries: list[dict]):
    """Validate the ZIP index and per-entry metadata without rereading file bodies."""
    try:
        with zipfile.ZipFile(path, 'r') as candidate:
            actual_entries = candidate.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveCacheError('The completed archive index is invalid.', 'validation_failed') from exc
    if len(actual_entries) != len(expected_entries):
        raise ArchiveCacheError('The completed archive has an unexpected file count.', 'validation_failed')
    for actual, expected in zip(actual_entries, expected_entries, strict=True):
        if (
            actual.filename != expected['relative_path']
            or actual.file_size != expected['size']
            or actual.compress_size != expected['size']
            or actual.compress_type != zipfile.ZIP_STORED
            or actual.CRC != expected['crc32']
        ):
            raise ArchiveCacheError(
                f'Archive validation failed at {expected["relative_path"]}.',
                'validation_failed',
            )


class ArchiveLease:
    def __init__(self, connection, resource):
        self.connection = connection
        self.resource = resource

    def release(self):
        if self.connection is None:
            return
        try:
            if self.connection.dialect.name == 'postgresql':
                self.connection.execute(text(
                    'SELECT pg_advisory_unlock(:namespace, :resource)'
                ), {'namespace': 139822755, 'resource': self.resource})
        except BaseException:
            self.connection.invalidate()
            raise
        finally:
            self.connection.close()
            self.connection = None


def acquire_archive_lease(archive_id: str):
    """Prevent eviction while a cached archive is being opened or streamed."""
    resource = int.from_bytes(hashlib.sha256(archive_id.encode()).digest()[:4], 'big') & 0x7fffffff
    from sharewarez.utils.download_limits import download_lock_engine
    connection = download_lock_engine(db.engine).connect()
    if connection.dialect.name != 'postgresql':
        return ArchiveLease(connection, resource)
    try:
        acquired = bool(connection.execute(text(
            'SELECT pg_try_advisory_lock(:namespace, :resource)'
        ), {'namespace': 139822755, 'resource': resource}).scalar())
        if not acquired:
            connection.close()
            return None
        connection.commit()
        return ArchiveLease(connection, resource)
    except BaseException:
        connection.invalidate()
        connection.close()
        raise


def archive_policy(settings_record=None):
    if settings_record is None:
        settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    values = dict(DEFAULT_POLICY)
    values.update(dict(getattr(settings_record, 'settings', None) or {}))
    return values


def cache_root() -> Path:
    configured = current_app.config.get('DOWNLOAD_CACHE_DIR')
    return Path(configured).expanduser().resolve()


def ensure_cache_root() -> Path:
    root = cache_root()
    static_root = Path(current_app.static_folder).resolve()
    if root == static_root or static_root in root.parents:
        raise ArchiveCacheError('Download cache cannot be inside the public static directory.', 'unsafe_cache_path')
    root.mkdir(parents=True, exist_ok=True)
    if not os.access(root, os.W_OK | os.X_OK):
        raise ArchiveCacheError('Download cache directory is not writable.', 'cache_not_writable')
    return root


def cache_health() -> dict:
    try:
        root = ensure_cache_root()
        usage = shutil.disk_usage(root)
        return {
            'healthy': True, 'path': str(root), 'free_bytes': usage.free,
            'total_bytes': usage.total, 'message': 'Cache storage is ready.',
        }
    except (ArchiveCacheError, OSError) as exc:
        return {
            'healthy': False, 'path': str(cache_root()), 'free_bytes': 0,
            'total_bytes': 0, 'message': str(exc),
        }


def _excluded_folder_names(settings_record=None) -> set[str]:
    names = {'updates', 'extras'}
    if settings_record is None:
        settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    if settings_record is not None:
        names.add((settings_record.update_folder_name or 'updates').lower())
        names.add((settings_record.extras_folder_name or 'extras').lower())
    return names


def build_source_manifest(source_path: str, settings_record=None) -> tuple[str, list[dict], int]:
    """Return a metadata fingerprint, canonical file manifest, and total bytes."""
    source = Path(source_path).resolve()
    if not source.is_dir():
        raise ArchiveCacheError('Archive source is not a directory.', 'source_not_directory')
    allowed = get_allowed_base_directories(current_app)
    safe, message = is_safe_path(str(source), allowed)
    if not safe:
        raise ArchiveCacheError(message or 'Archive source is outside allowed storage.', 'unsafe_source')

    excluded = _excluded_folder_names(settings_record)
    entries = []
    for root, dirs, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(
            name for name in dirs
            if name.lower() not in excluded and not (root_path / name).is_symlink()
        )
        for name in sorted(files):
            if name.lower() == 'sharewarez.json':
                continue
            path = root_path / name
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if source not in resolved.parents:
                raise ArchiveCacheError('Archive entry escaped its source directory.', 'unsafe_source_entry')
            stat = resolved.stat()
            entries.append({
                'relative_path': resolved.relative_to(source).as_posix(),
                'path': str(resolved),
                'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns,
            })
    entries.sort(key=lambda item: item['relative_path'].encode('utf-8'))
    canonical = {
        'version': ARCHIVE_FORMAT_VERSION,
        'source': str(source),
        'excluded': sorted(excluded),
        'entries': [
            [item['relative_path'], item['size'], item['mtime_ns']] for item in entries
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    return fingerprint, entries, sum(item['size'] for item in entries)


def resolved_archive_path(archive: DownloadArchive, *, require_ready=True) -> Path:
    if require_ready and archive.state != 'ready':
        raise ArchiveCacheError('Archive is not ready.', 'archive_not_ready')
    if not archive.relative_path:
        raise ArchiveCacheError('Archive file is unavailable.', 'archive_missing')
    root = ensure_cache_root()
    target = (root / archive.relative_path).resolve()
    if root not in target.parents:
        raise ArchiveCacheError('Archive path escaped the cache directory.', 'unsafe_archive_path')
    if require_ready and not target.is_file():
        raise ArchiveCacheError('Archive file is missing.', 'archive_missing')
    return target


def request_resumable_archive(download_request: DownloadRequest, display_name=None):
    """Attach a directory request to one deduplicated archive build."""
    settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    policy = archive_policy(settings_record)
    if policy['archiveCacheMode'] == 'off' or not os.path.isdir(download_request.file_location or ''):
        return None
    health = cache_health()
    if not health['healthy']:
        if policy['archiveCacheMode'] == 'prefer' and policy['archiveCacheFallbackEnabled']:
            download_request.delivery_kind = 'live_archive'
            download_request.status = 'available'
            return None
        raise ArchiveCacheError(health['message'], 'cache_unavailable')

    cache_key, entries, source_bytes = build_source_manifest(
        download_request.file_location, settings_record,
    )
    archive = db.session.scalar(
        select(DownloadArchive).where(
            DownloadArchive.cache_key == cache_key
        ).with_for_update()
    )
    safe_name = secure_filename(display_name or f'{Path(download_request.file_location).name}.zip')
    if not safe_name:
        safe_name = 'download.zip'
    if archive is None:
        try:
            with db.session.begin_nested():
                archive = DownloadArchive(
                    cache_key=cache_key,
                    source_path=str(Path(download_request.file_location).resolve()),
                    display_name=safe_name,
                    state='queued', source_bytes=source_bytes, file_count=len(entries),
                    format_version=ARCHIVE_FORMAT_VERSION,
                )
                db.session.add(archive)
                db.session.flush()
        except IntegrityError:
            archive = db.session.scalar(
                select(DownloadArchive).where(
                    DownloadArchive.cache_key == cache_key
                ).with_for_update()
            )
    if archive is None:
        raise ArchiveCacheError('The archive could not be reserved.', 'archive_reservation_failed')
    download_request.archive_id = archive.id
    download_request.delivery_kind = 'cached_archive'
    if archive.state == 'ready':
        try:
            resolved_archive_path(archive)
            download_request.status = 'available'
            archive.last_accessed_at = datetime.now(timezone.utc)
            return archive
        except ArchiveCacheError:
            archive.state = 'failed'
            archive.failure_code = 'archive_missing'
            archive.failure_message = 'The cached file is missing and must be rebuilt.'
    download_request.status = 'processing'
    if archive.state in {'failed', 'deleting'}:
        archive.state = 'queued'
        archive.failure_code = archive.failure_message = None
    if archive.build_job_id is None:
        from sharewarez.utils.background_jobs import enqueue
        job = enqueue(
            'download.archive.build', {'archive_id': archive.id},
            queue='archive', max_attempts=3, created_by_id=download_request.user_id,
            commit=False,
        )
        archive.build_job_id = job.id
    return archive


def _capacity_preflight(archive: DownloadArchive):
    policy = archive_policy()
    health = cache_health()
    if not health['healthy']:
        raise ArchiveCacheError(health['message'], 'cache_unavailable')
    maximum = round(float(policy['archiveCacheMaxGb']) * 1_000_000_000)
    minimum_free = round(float(policy['archiveCacheMinFreeGb']) * 1_000_000_000)
    reserved = db.session.scalar(
        select(func.coalesce(func.sum(
            func.coalesce(func.nullif(DownloadArchive.archive_bytes, 0), DownloadArchive.source_bytes)
        ), 0)).where(
            DownloadArchive.state.in_(('ready', 'building')),
            DownloadArchive.id != archive.id,
        )
    ) or 0
    estimated = archive.source_bytes + max(1_048_576, archive.file_count * 1024)
    if reserved + estimated > maximum:
        cleanup_cache(required_bytes=estimated)
        reserved = db.session.scalar(
            select(func.coalesce(func.sum(
                func.coalesce(
                    func.nullif(DownloadArchive.archive_bytes, 0), DownloadArchive.source_bytes,
                )
            ), 0)).where(
                DownloadArchive.state.in_(('ready', 'building')),
                DownloadArchive.id != archive.id,
            )
        ) or 0
    if reserved + estimated > maximum:
        raise ArchiveCacheError('Cache size limit cannot accommodate this archive.', 'cache_limit')
    if health['free_bytes'] - estimated < minimum_free:
        cleanup_cache(required_bytes=estimated)
        health = cache_health()
    if health['free_bytes'] - estimated < minimum_free:
        raise ArchiveCacheError('Not enough free cache storage to prepare this archive.', 'insufficient_storage')


def build_archive(context, archive_id: str) -> dict:
    """Persistent job handler that publishes one validated immutable ZIP."""
    archive = db.session.get(DownloadArchive, archive_id)
    if archive is None:
        raise ValueError(f'Download archive not found: {archive_id}')
    if archive.state == 'ready':
        try:
            path = resolved_archive_path(archive)
            return {'archive_id': archive.id, 'archive_bytes': path.stat().st_size, 'reused': True}
        except ArchiveCacheError:
            pass

    partial = None
    try:
        archive.state = 'building'
        archive.failure_code = archive.failure_message = None
        archive.bytes_written = 0
        archive.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        context.heartbeat(1, f'Preparing {archive.display_name}')
        cache_key, entries, source_bytes = build_source_manifest(archive.source_path)
        if cache_key != archive.cache_key:
            raise ArchiveCacheError('Source files changed before preparation started.', 'source_changed')
        if not entries:
            raise ArchiveCacheError('The source folder contains no downloadable files.', 'empty_source')
        archive.source_bytes = source_bytes
        archive.file_count = len(entries)
        _capacity_preflight(archive)
        root = ensure_cache_root()
        partial = root / f'{archive.id}.{context.job_id}.partial'
        final = root / f'{archive.cache_key}.zip'
        written_source = 0
        last_heartbeat = 0
        expected_entries = []
        with partial.open('wb') as completed:
            writer = _HashingArchiveWriter(completed)
            with zipfile.ZipFile(
                writer, 'w', compression=zipfile.ZIP_STORED, allowZip64=True,
            ) as output:
                for index, entry in enumerate(entries, start=1):
                    context.check_cancelled()
                    current = Path(entry['path']).stat()
                    if current.st_size != entry['size'] or current.st_mtime_ns != entry['mtime_ns']:
                        raise ArchiveCacheError('Source files changed during preparation.', 'source_changed')
                    archive_info = zipfile.ZipInfo.from_file(
                        entry['path'], arcname=entry['relative_path'], strict_timestamps=False,
                    )
                    archive_info.compress_type = zipfile.ZIP_STORED
                    with Path(entry['path']).open('rb') as source_file:
                        with output.open(archive_info, 'w', force_zip64=True) as archive_file:
                            for chunk in iter(lambda: source_file.read(2 * 1024 * 1024), b''):
                                context.check_cancelled()
                                archive_file.write(chunk)
                                written_source += len(chunk)
                                progress = min(
                                    97, max(1, round(written_source / max(1, source_bytes) * 97)),
                                )
                                if progress != last_heartbeat:
                                    archive.bytes_written = writer.tell()
                                    archive.updated_at = datetime.now(timezone.utc)
                                    context.heartbeat(
                                        progress, f'Adding file {index} of {len(entries)}',
                                    )
                                    last_heartbeat = progress
                    if archive_info.file_size != entry['size']:
                        raise ArchiveCacheError(
                            f'Archive write verification failed at {entry["relative_path"]}.',
                            'validation_failed',
                        )
                    expected_entries.append({
                        'relative_path': entry['relative_path'],
                        'size': entry['size'],
                        'crc32': archive_info.CRC,
                    })
                    after = Path(entry['path']).stat()
                    if after.st_size != entry['size'] or after.st_mtime_ns != entry['mtime_ns']:
                        raise ArchiveCacheError('Source files changed during preparation.', 'source_changed')
            completed.flush()
            os.fsync(completed.fileno())
            archive_digest = writer.digest.hexdigest()
            archive_size = writer.tell()
        context.heartbeat(98, 'Checking archive index')
        _validate_archive_index(partial, expected_entries)
        context.heartbeat(99, 'Publishing resumable archive')
        os.replace(partial, final)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        now = datetime.now(timezone.utc)
        archive.state = 'ready'
        archive.relative_path = final.name
        archive.archive_bytes = archive_size
        archive.bytes_written = archive.archive_bytes
        archive.sha256 = archive_digest
        archive.ready_at = archive.updated_at = archive.last_accessed_at = now
        archive.build_job_id = None
        requests = db.session.execute(
            select(DownloadRequest).where(
                DownloadRequest.archive_id == archive.id,
                DownloadRequest.status == 'processing',
            )
        ).scalars().all()
        for download_request in requests:
            download_request.status = 'available'
            download_request.completion_time = now
        db.session.commit()
        if requests:
            from sharewarez.utils.notification_events import publish_event
            publish_event(
                [item.user_id for item in requests], 'download_archive_ready',
                'Resumable download ready', f'{archive.display_name} is ready to download.',
                link_url='/downloads', dedupe_key=f'download-archive-ready:{archive.id}',
                resource_type='download_archive', resource_id=archive.id,
            )
        context.heartbeat(100, 'Resumable archive ready')
        return {'archive_id': archive.id, 'archive_bytes': archive.archive_bytes, 'reused': False}
    except Exception as exc:
        if partial is not None:
            partial.unlink(missing_ok=True)
        db.session.rollback()
        from sharewarez.utils.background_jobs import JobCancelled
        if isinstance(exc, JobCancelled):
            raise
        archive = db.session.get(DownloadArchive, archive_id)
        if archive is not None:
            archive.state = 'failed'
            archive.failure_code = getattr(exc, 'code', 'build_failed')
            archive.failure_message = str(exc)[:512]
            archive.updated_at = datetime.now(timezone.utc)
            db.session.commit()
        raise


@contextmanager
def _cleanup_lock():
    connection = db.engine.connect()
    acquired = True
    try:
        if connection.dialect.name == 'postgresql':
            acquired = bool(connection.execute(text(
                'SELECT pg_try_advisory_lock(:namespace, :resource)'
            ), {'namespace': 139822755, 'resource': 1}).scalar())
        yield acquired
    finally:
        if acquired and connection.dialect.name == 'postgresql':
            connection.execute(text(
                'SELECT pg_advisory_unlock(:namespace, :resource)'
            ), {'namespace': 139822755, 'resource': 1})
        connection.close()


def cleanup_cache(*, required_bytes=0, clear_unused=False) -> dict:
    """Evict eligible archives by retention and then LRU until capacity is available."""
    with _cleanup_lock() as acquired:
        if not acquired:
            return {'removed': 0, 'removed_bytes': 0, 'skipped': True}
        return _cleanup_cache_locked(required_bytes=required_bytes, clear_unused=clear_unused)


def _cleanup_cache_locked(*, required_bytes=0, clear_unused=False) -> dict:
    root = ensure_cache_root()
    policy = archive_policy()
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(policy['archiveCacheRetentionDays']))
    active_ids = set(db.session.execute(
        select(DownloadTransfer.archive_id).where(
            DownloadTransfer.status == 'active', DownloadTransfer.archive_id.is_not(None),
        )
    ).scalars())
    candidates = db.session.execute(
        select(DownloadArchive).where(
            DownloadArchive.state.in_(('ready', 'failed')),
            DownloadArchive.pinned.is_(False),
        ).order_by(DownloadArchive.last_accessed_at.asc().nullsfirst(), DownloadArchive.created_at.asc())
    ).scalars().all()
    maximum = round(float(policy['archiveCacheMaxGb']) * 1_000_000_000)
    minimum_free = round(float(policy['archiveCacheMinFreeGb']) * 1_000_000_000)
    used = db.session.scalar(
        select(func.coalesce(func.sum(DownloadArchive.archive_bytes), 0)).where(
            DownloadArchive.state == 'ready'
        )
    ) or 0
    free = shutil.disk_usage(root).free
    removed = removed_bytes = 0
    for archive in candidates:
        expired = archive.state == 'failed' or not archive.last_accessed_at or archive.last_accessed_at < cutoff
        pressure = used + required_bytes > maximum or free - required_bytes < minimum_free
        if archive.id in active_ids or not (clear_unused or expired or pressure):
            continue
        lease = acquire_archive_lease(archive.id)
        if lease is None:
            continue
        try:
            path = resolved_archive_path(archive, require_ready=False) if archive.relative_path else None
            freed_disk_bytes = path.stat().st_size if path and path.is_file() else 0
            archive.state = 'deleting'
            db.session.commit()
            if path:
                path.unlink(missing_ok=True)
            removed += 1
            removed_bytes += archive.archive_bytes
            used -= archive.archive_bytes
            free += freed_disk_bytes
            fallback = policy['archiveCacheMode'] != 'require' and policy['archiveCacheFallbackEnabled']
            db.session.execute(
                update(DownloadRequest).where(DownloadRequest.archive_id == archive.id).values(
                    archive_id=None,
                    delivery_kind='live_archive' if fallback else 'cached_archive',
                    status='available' if fallback else 'failed',
                )
            )
            db.session.delete(archive)
            db.session.commit()
        except Exception:
            db.session.rollback()
            archive = db.session.get(DownloadArchive, archive.id)
            if archive:
                archive.state = 'failed'
                archive.failure_code = 'eviction_failed'
                archive.failure_message = 'The cached file could not be removed.'
                db.session.commit()
        finally:
            lease.release()
    return {'removed': removed, 'removed_bytes': removed_bytes}


def archive_summary() -> dict:
    policy = archive_policy()
    health = cache_health()
    counts = dict(db.session.execute(select(
        DownloadArchive.state, func.count(DownloadArchive.id),
    ).group_by(DownloadArchive.state)).all())
    ready_bytes, reclaimable_bytes = db.session.execute(select(
        func.coalesce(func.sum(DownloadArchive.archive_bytes), 0),
        func.coalesce(func.sum(DownloadArchive.archive_bytes).filter(DownloadArchive.pinned.is_(False)), 0),
    ).where(DownloadArchive.state == 'ready')).one()
    return {
        'policy': policy,
        'health': health,
        'used_bytes': int(ready_bytes),
        'ready_bytes': int(ready_bytes),
        'reclaimable_bytes': int(reclaimable_bytes),
        'counts': {state: counts.get(state, 0) for state in ARCHIVE_STATES},
    }


def reconcile_cache() -> dict:
    """Clean interrupted partials and invalidate database rows whose files disappeared."""
    root = ensure_cache_root()
    partials_removed = 0
    for partial in root.glob('*.partial'):
        partial.unlink(missing_ok=True)
        partials_removed += 1

    invalidated = 0
    ready_archives = db.session.execute(
        select(DownloadArchive).where(DownloadArchive.state == 'ready')
    ).scalars().all()
    for archive in ready_archives:
        try:
            resolved_archive_path(archive)
        except ArchiveCacheError:
            archive.state = 'failed'
            archive.build_job_id = None
            archive.failure_code = 'archive_missing'
            archive.failure_message = 'The cached file is missing and must be rebuilt.'
            db.session.query(DownloadRequest).filter(
                DownloadRequest.archive_id == archive.id,
                DownloadRequest.status == 'available',
            ).update({'status': 'failed'}, synchronize_session=False)
            invalidated += 1
    db.session.commit()
    return {'partials_removed': partials_removed, 'invalidated': invalidated}
