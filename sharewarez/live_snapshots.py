"""Authorized, read-only snapshots shared by live download transports."""

from datetime import datetime, timezone

from flask import Request
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from sharewarez import db
from sharewarez.models import DownloadArchive, DownloadRequest, DownloadTransfer, User
from sharewarez.utils.functions import format_duration, format_size
from sharewarez.transfer_rates import transfer_rates


class LiveAccessDenied(Exception):
    def __init__(self, status=401):
        self.status = status


def download_payload(item, policy):
    archive = item.archive
    return {
        "id": item.id, "status": item.status, "delivery_kind": item.delivery_kind,
        "available": item.status == "available", "size_label": format_size(item.download_size),
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "fallback_available": bool(archive and policy["archiveCacheMode"] == "prefer"
                                   and policy["archiveCacheFallbackEnabled"]),
        "archive": ({
            "state": archive.state,
            "progress": min(99, round(archive.bytes_written / archive.source_bytes * 100))
            if archive.source_bytes and archive.state in {"queued", "building"} else None,
            "failure_message": archive.failure_message,
        } if archive else None),
    }


def cache_payload(ids):
    from sharewarez.utils.download_cache import archive_summary
    summary = archive_summary()
    archives = db.session.execute(select(DownloadArchive).options(joinedload(DownloadArchive.build_job)).where(
        DownloadArchive.id.in_(ids),
    )).scalars().all()
    leases = dict(db.session.execute(select(DownloadTransfer.archive_id, func.count()).where(
        DownloadTransfer.archive_id.in_(ids), DownloadTransfer.status == "active",
    ).group_by(DownloadTransfer.archive_id)).all())
    return {
        "summary": {
            "healthy": summary["health"]["healthy"], "message": summary["health"]["message"],
            "used_bytes": summary["used_bytes"], "free_bytes": summary["health"]["free_bytes"],
            "reclaimable_bytes": summary["reclaimable_bytes"], "counts": summary["counts"],
        },
        "archives": [{
            "id": item.id, "state": item.state, "pinned": item.pinned, "file_count": item.file_count,
            "source_bytes": item.source_bytes, "archive_bytes": item.archive_bytes,
            "bytes_written": item.bytes_written, "failure_message": item.failure_message,
            "active_leases": leases.get(item.id, 0),
            "last_accessed_at": item.last_accessed_at.isoformat() if item.last_accessed_at else None,
            "cancel_requested": bool(item.build_job and item.build_job.cancel_requested),
            "progress": min(99, max(0, item.build_job.progress or 0)) if item.build_job
            else min(99, round(item.bytes_written / item.source_bytes * 100)) if item.source_bytes else 0,
            "progress_message": item.build_job.progress_message if item.build_job else None,
        } for item in archives],
    }


def authenticate(app, scope, view):
    headers = dict(scope.get("headers", []))
    request = Request({
        "REQUEST_METHOD": "GET", "PATH_INFO": "/api/live/downloads",
        "SERVER_NAME": "localhost", "SERVER_PORT": "80",
        "wsgi.url_scheme": scope.get("scheme", "http"),
        "HTTP_COOKIE": headers.get(b"cookie", b"").decode("latin1"),
    })
    session = app.session_interface.open_session(app, request)
    try:
        user_id = int((session or {}).get("_user_id", ""))
    except (ValueError, TypeError):
        raise LiveAccessDenied() from None
    user = db.session.get(User, user_id)
    if user is None or not user.state:
        raise LiveAccessDenied()
    if view != "downloads" and user.role != "admin":
        raise LiveAccessDenied(403)
    return user


def transfer_payload(transfer, now, *, admin=False):
    elapsed = max(0, (now - transfer.started_at).total_seconds())
    sent, expected = transfer.bytes_sent, transfer.reserved_bytes
    current_speed = transfer_rates.observe(transfer.id, sent, now.timestamp(), transfer.last_activity_at.timestamp())
    result = {
        "id": transfer.id, "download_request_id": transfer.download_request_id,
        "bytes_sent": sent, "expected_bytes": expected,
        "bytes_sent_label": format_size(sent) if sent else "0 B",
        "expected_bytes_label": format_size(expected) if expected else None,
        "progress": min(100, round(sent / expected * 100, 1)) if expected else None,
        "elapsed_seconds": int(elapsed), "elapsed_label": format_duration(elapsed),
        "average_speed": sent / elapsed if elapsed > 0 else None,
        "current_speed": current_speed,
        "eta_seconds": (expected - sent) / current_speed
        if expected > sent and current_speed and current_speed > 0 else None,
        "last_activity_at": transfer.last_activity_at.isoformat(),
    }
    if admin:
        result.update(username=transfer.user.name, filename=transfer.filename)
    return result


def snapshot(app, scope, view, ids, *, cache=None):
    """Reauthorize every call; share only short-lived, correctly scoped data."""
    with app.app_context():
        user = authenticate(app, scope, view)
        user_id = user.id
        # Release the authentication transaction before waiting for the cache lock.
        db.session.remove()
        key = (view, user_id if view == "downloads" else None, tuple(sorted(ids)))
        loader = lambda: snapshot_data(view, ids, user_id)
        data = cache.get(key, loader) if cache is not None else loader()
        return {**data, "user_id": user_id}


def snapshot_data(view, ids, user_id):
    now = datetime.now(timezone.utc)
    result = {"view": view, "server_time": now.isoformat()}
    if view in {"downloads", "activity"}:
        query = select(DownloadTransfer).where(DownloadTransfer.status == "active")
        if view == "downloads":
            query = query.where(DownloadTransfer.user_id == user_id)
        else:
            query = query.options(joinedload(DownloadTransfer.user))
        transfers = db.session.execute(query.order_by(DownloadTransfer.id).limit(1001)).scalars().all()
        result["transfers_truncated"] = len(transfers) > 1000
        result["transfers"] = [transfer_payload(item, now, admin=view == "activity") for item in transfers[:1000]]
    if view == "downloads":
        from sharewarez.utils.download_cache import archive_policy
        downloads = db.session.execute(select(DownloadRequest).options(joinedload(DownloadRequest.archive)).where(
            DownloadRequest.user_id == user_id, DownloadRequest.id.in_(ids),
        )).scalars().all()
        policy = archive_policy()
        result["downloads"] = [download_payload(item, policy) for item in downloads]
    if view == "cache":
        result.update(cache_payload(ids))
    return result
