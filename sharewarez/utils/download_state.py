"""Read-only link presentation and guarded transitions shared by every entry point."""
import os
from pathlib import Path
from flask import current_app
from datetime import datetime, timezone

from sqlalchemy import and_, func, select

from sharewarez import db
from sharewarez.models import DownloadRequest, DownloadTransfer, GlobalSettings, User
from sharewarez.utils.download_cache import ArchiveCacheError, archive_policy, build_source_manifest, cache_root, request_resumable_archive
from sharewarez.utils.download_limits import calculate_download_expiry
from sharewarez.utils.download_sources import direct_package_path
from sharewarez.utils.functions import format_size
from sharewarez.utils.transfer_evidence import transfer_byte_label

_AUTO = object()


def source_path(link):
    return link.file_location or link.zip_file_path


def delivery_path(link):
    return link.zip_file_path or source_path(link)


def validated_source(link):
    from sharewarez.utils.download_creation import validate_download_source
    return validate_download_source(source_path(link))


def cached_path(archive):
    if not archive or archive.state != 'ready' or not archive.relative_path:
        return None
    try:
        root = cache_root().resolve()
        static = Path(current_app.static_folder).resolve()
        if root == static or static in root.parents:
            return None
        path = (root / archive.relative_path).resolve()
        if root in path.parents and path.is_file() and os.access(path, os.R_OK):
            return str(path)
    except (OSError, ValueError, TypeError):
        pass
    return None


def transfer_context(links):
    ids = [link.id for link in links if link.id is not None]
    if not ids:
        return {}, {}
    owned = and_(DownloadTransfer.download_request_id == DownloadRequest.id, DownloadTransfer.user_id == DownloadRequest.user_id)
    ranked = select(DownloadTransfer.id, func.row_number().over(
        partition_by=DownloadTransfer.download_request_id,
        order_by=(DownloadTransfer.started_at.desc(), DownloadTransfer.id.desc()),
    ).label('position')).join(DownloadRequest, owned).where(DownloadTransfer.download_request_id.in_(ids)).subquery()
    latest = db.session.scalars(select(DownloadTransfer).join(ranked, ranked.c.id == DownloadTransfer.id).where(ranked.c.position == 1).execution_options(populate_existing=True)).all()
    active = db.session.scalars(select(DownloadTransfer).join(DownloadRequest, owned).where(
        DownloadTransfer.download_request_id.in_(ids), DownloadTransfer.status == 'active'
    ).order_by(DownloadTransfer.started_at.desc(), DownloadTransfer.id.desc()).limit(2001).execution_options(populate_existing=True)).all()
    active_map: dict[int, DownloadTransfer] = {}
    for row in active:
        active_map.setdefault(row.download_request_id, row)
    return active_map, {row.download_request_id: row for row in latest}


def attempt_payload(row):
    if row is None:
        return None
    expected = row.expected_response_bytes
    if expected is None and row.delivery_kind != 'live_archive':
        expected = row.reserved_bytes
    return {'id': row.id, 'download_request_id': row.download_request_id, 'status': row.status,
            'end_reason': row.end_reason, 'end_reason_label': row.end_reason_label,
            'bytes_sent': row.bytes_sent, 'bytes_sent_label': transfer_byte_label(row.bytes_sent),
            'summary': row.end_reason_label + ' · ' + transfer_byte_label(row.bytes_sent) + ' server-sent',
            'expected_bytes': expected, 'expected_bytes_label': transfer_byte_label(expected) if expected is not None else None,
            'progress': min(100, round(row.bytes_sent / expected * 100, 1)) if expected else None,
            'delivery_kind': row.delivery_kind, 'correlation_id': row.correlation_id}


def archive_failure_message(archive):
    messages = {
        'build_cancelled': 'An administrator stopped archive preparation. Retry to prepare it again.',
        'cache_limit': 'Download storage cannot fit this archive. Ask an administrator to check capacity, then retry.',
        'insufficient_storage': 'Download storage has insufficient free space. Ask an administrator to check it, then retry.',
        'source_changed': 'Game files changed during preparation. Retry to build a fresh archive.',
        'source_unreadable': 'Some game files could not be read. Ask an administrator to check them, then retry.',
        'empty_source': 'No downloadable game files were found. Ask an administrator to check storage.',
        'archive_missing': 'The prepared archive is unavailable. Retry to rebuild it.',
    }
    if archive and archive.state == 'ready':
        return messages['archive_missing']
    return messages.get((archive.failure_code or "") if archive else "", 'Resumable preparation is unavailable. Retry or ask an administrator to check download storage.')


def download_state(link, policy=None, *, active=_AUTO, latest=_AUTO, now=None):
    policy = policy or archive_policy()
    if active is _AUTO or latest is _AUTO:
        active_map, latest_map = transfer_context([link])
        active = active_map.get(link.id) if active is _AUTO else active
        latest = latest_map.get(link.id) if latest is _AUTO else latest
    now = now or datetime.now(timezone.utc)
    expiry = link.expires_at
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    archive = link.archive
    progress = min(99, round(archive.bytes_written / archive.source_bytes * 100)) if archive and archive.source_bytes and archive.state in {'queued', 'building'} else None
    result = {'id': link.id, 'status': link.status, 'stored_status': link.status, 'delivery_kind': link.delivery_kind,
              'size_label': format_size(link.download_size), 'expires_at': expiry.isoformat() if expiry else None,
              'active_transfer': attempt_payload(active), 'latest_attempt': attempt_payload(latest),
              'retry_label': 'Retry', 'message': '', 'recovery_message': '', 'archive_progress': progress,
              'expiry_label': 'Available until ' + expiry.astimezone(timezone.utc).strftime('%d %b %Y %H:%M UTC') if expiry else '',
              'archive': {'state': archive.state, 'progress': progress, 'failure_message': archive_failure_message(archive) if archive.state == 'failed' else None} if archive else None}

    def state(status, label, delivery, actions, message='', delivery_class='unavailable'):
        result.update(status=status, display_status=label, delivery_label=delivery,
                      delivery_class=delivery_class, allowed_actions=actions, message=message,
                      available='download' in actions, fallback_available='fallback' in actions,
                      expiring_soon=bool(expiry and status == 'available' and 0 < (expiry - now).total_seconds() <= 86400))
        if status == 'available' and latest and latest.status in {'interrupted', 'cancelled'}:
            same_file = latest.delivery_kind == 'direct' and result['delivery_kind'] == 'direct'
            same_archive = latest.delivery_kind == 'cached_archive' and archive and latest.archive_id == archive.id
            if delivery_class == 'resumable' and (same_file or same_archive):
                result['recovery_message'] = "Use your browser's Downloads list when it offers Resume. Download here starts a new response."
            elif delivery_class == 'streaming':
                result['recovery_message'] = 'Live ZIPs restart from the beginning. Download again to start a new response.'
            elif delivery_class == 'resumable':
                result['recovery_message'] = 'This prepared file differs from the earlier stream. Download again to start a new response.'
        return result

    if active:
        kind = active.delivery_kind
        if kind is None:
            return state('downloading', 'Downloading', 'Downloading', [])
        resumable = kind in {'direct', 'cached_archive'}
        return state('downloading', 'Downloading', 'Resumable' if resumable else 'Streaming · restart required', [], delivery_class='resumable' if resumable else 'streaming')
    if link.status == 'expired' or (expiry and expiry <= now):
        result['retry_label'] = 'Renew'
        return state('expired', 'Expired', 'Unavailable', ['retry'], 'This link expired. Renew it to validate the source and prepare it again.')
    if link.status == 'cancelled':
        return state('cancelled', 'Cancelled', 'Unavailable', ['retry'], 'Retry to validate the source and prepare this link again.')
    if link.status in {'available', 'completed'} and cached_path(archive):
        return state('available', 'Ready', 'Resumable', ['download', 'delete'], delivery_class='resumable')
    source, source_error = None, None
    try:
        source = validated_source(link)
    except (ValueError, OSError):
        source_error = 'The source is unavailable. Ask an administrator to check game storage, then retry.'
    directory = bool(source and os.path.isdir(source))
    fallback = bool(directory and policy['archiveCacheMode'] == 'prefer' and policy['archiveCacheFallbackEnabled'])
    if source_error:
        return state('failed', 'Failed', 'Unavailable', ['delete'], source_error)
    if link.status == 'failed' or (archive and archive.state in {'failed', 'deleting', 'ready'}):
        return state('failed', 'Failed', 'Unavailable', ['retry', *(['fallback'] if fallback else []), 'delete'], archive_failure_message(archive) if directory else 'Retry to validate this download again.')
    if link.status in {'pending', 'processing', 'available'} and archive and archive.state in {'queued', 'building'}:
        return state('processing', 'Preparing', 'Preparing', ['cancel', *(['fallback'] if fallback else [])], delivery_class='preparing')
    path = delivery_path(link)
    if link.status in {'available', 'completed'} and path and os.path.isfile(path):
        from sharewarez.utils.download_creation import validate_download_source
        try:
            validate_download_source(path)
        except (ValueError, OSError):
            return state('failed', 'Failed', 'Unavailable', ['retry', 'delete'], 'The prepared file is unavailable. Retry to validate the source.')
        return state('available', 'Ready', 'Resumable', ['download', 'delete'], delivery_class='resumable')
    if link.status in {'available', 'completed'} and directory and not archive and (policy['archiveCacheMode'] == 'off' or (link.delivery_kind == 'live_archive' and fallback)):
        return state('available', 'Ready', 'Streaming · restart required', ['download', 'delete'], delivery_class='streaming')
    return state('failed', 'Failed', 'Unavailable', ['retry', *(['fallback'] if fallback else []), 'delete'], 'This link needs preparation. Retry to validate its source.')


def download_states(links, policy=None):
    links = list(links)
    policy = policy or archive_policy()
    active, latest = transfer_context(links)
    return [download_state(link, policy, active=active.get(link.id), latest=latest.get(link.id)) for link in links]


def prepare_download(link, settings=None, *, package=None, size=None):
    source = validated_source(link)
    settings = settings or db.session.scalar(select(GlobalSettings))
    if package is None:
        if os.path.isdir(source):
            _, entries, size = build_source_manifest(source, settings)
            package = direct_package_path(source, entries) if link.content_type == 'game' else source
        else:
            package = source
        if os.path.isfile(package):
            size = os.path.getsize(package)
    # Validate before changing expiry, representation or state.
    link.file_location, link.zip_file_path = source, package
    link.download_size = size or 0
    link.archive_id = None
    link.status = 'available'
    link.delivery_kind = 'direct' if os.path.isfile(package) else 'live_archive'
    link.expires_at = calculate_download_expiry(settings)
    link.completion_time = None
    if os.path.isdir(package):
        try:
            request_resumable_archive(link)
        except ArchiveCacheError:
            link.status, link.delivery_kind = 'failed', 'cached_archive'
    db.session.flush()
    db.session.expire(link, ['archive'])
    return link


def lock_download(download_id, *, owner_id=None):
    link = db.session.scalar(select(DownloadRequest).where(DownloadRequest.id == download_id))
    if link is None or (owner_id is not None and link.user_id != owner_id):
        return None
    db.session.execute(select(User).where(User.id == link.user_id).with_for_update()).scalar_one()
    return db.session.scalar(select(DownloadRequest).where(DownloadRequest.id == download_id).with_for_update().execution_options(populate_existing=True))


def apply_action(link, action, *, admin=False):
    state = download_state(link)
    administrative = admin and action in {'cancel', 'delete'} and not state['active_transfer'] and (action == 'delete' or link.status not in {'cancelled', 'expired'})
    if action not in state['allowed_actions'] and not administrative:
        return False, state['message'] or 'This action is unavailable while the download is active or its state has changed.'
    if action == 'retry':
        try:
            prepare_download(link)
        except (ValueError, OSError, ArchiveCacheError):
            return False, 'The source could not be validated. Ask an administrator to check storage and retry.'
    elif action == 'fallback':
        try:
            source = validated_source(link)
        except (ValueError, OSError):
            return False, 'The source is unavailable. Ask an administrator to check storage.'
        link.archive_id, link.zip_file_path = None, source
        link.delivery_kind, link.status = 'live_archive', 'available'
        db.session.flush()
        db.session.expire(link, ['archive'])
    elif action == 'cancel':
        link.status = 'cancelled'
    elif action == 'delete':
        db.session.delete(link)
    return True, {'delete': 'Download link removed.', 'cancel': 'Download request cancelled.', 'retry': 'Download preparation updated.', 'fallback': 'Streaming download is ready.'}.get(action, 'Download link updated.')