"""Transactional creation shared by game, update and extra initiation."""
import os
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import func, or_, select, update

from sharewarez import db
from sharewarez.models import DownloadRequest, GlobalSettings, User
from sharewarez.utils.download_cache import build_source_manifest, request_resumable_archive
from sharewarez.utils.download_sources import direct_package_path
from sharewarez.utils.download_limits import calculate_download_expiry
from sharewarez.utils.filename import sanitize_filename
from sharewarez.utils.security import get_allowed_base_directories, is_safe_path


def validate_download_source(source):
    if not source:
        raise ValueError('The source is unavailable. Ask an administrator to check game storage and scan again.')
    safe, _ = is_safe_path(source, get_allowed_base_directories(current_app))
    if not safe:
        raise ValueError('The source is outside configured game storage. Ask an administrator to check it.')
    if not (os.path.isfile(source) or os.path.isdir(source)) or not os.access(source, os.R_OK):
        raise ValueError('The source is missing or unreadable. Ask an administrator to check game storage and scan again.')
    return os.path.normpath(source)


def create_or_reuse_download(user_id, game, *, content_type='game', record=None):
    source = validate_download_source(game.full_disk_path if record is None else record.file_path)
    settings = db.session.scalar(select(GlobalSettings))
    if os.path.isdir(source):
        _, entries, size = build_source_manifest(source, settings)
        package = direct_package_path(source, entries) if content_type == 'game' else source
        if os.path.isfile(package):
            size = os.path.getsize(package)
    else:
        package, size = source, os.path.getsize(source)
    # Serialize all entry points for a member before looking up a reusable link.
    db.session.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
    update_id = record.id if content_type == 'update' else None
    extra_id = record.id if content_type == 'extra' else None
    matches = db.session.scalars(select(DownloadRequest).where(
        DownloadRequest.user_id == user_id, DownloadRequest.game_uuid == game.uuid,
        DownloadRequest.content_type == content_type, DownloadRequest.file_location == source,
        or_(DownloadRequest.game_update_id == update_id, DownloadRequest.game_update_id.is_(None)),
        or_(DownloadRequest.game_extra_id == extra_id, DownloadRequest.game_extra_id.is_(None)),
    ).order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc()).with_for_update()).all()
    if matches:
        if len(matches) > 1:
            current_app.logger.warning('Duplicate download links retained for review: request_ids=%s', [item.id for item in matches])
        # Keep historical IDs and transfer relationships intact; never merge/delete.
        return matches[0], False
    title = game.name if content_type == 'game' else (getattr(record, 'title', None) or getattr(record, 'name', None) or os.path.basename(source))
    link = DownloadRequest(user_id=user_id, game_uuid=game.uuid, content_type=content_type,
        content_title=title, game_update_id=update_id, game_extra_id=extra_id,
        file_location=source, zip_file_path=package, download_size=size, status='available',
        completion_time=datetime.now(timezone.utc), expires_at=calculate_download_expiry(settings),
        delivery_kind='direct' if os.path.isfile(package) else 'live_archive')
    db.session.add(link)
    counter = game if record is None else record
    model = type(counter)
    key = model.uuid == counter.uuid if record is None else model.id == counter.id
    db.session.execute(update(model).where(key).values(times_downloaded=func.coalesce(model.times_downloaded, 0) + 1))
    if os.path.isdir(package):
        request_resumable_archive(link, f'{sanitize_filename(title)}.zip')
    db.session.flush()
    return link, True