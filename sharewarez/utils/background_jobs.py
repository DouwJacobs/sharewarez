"""Persistent background-job queue primitives."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import socket
import time
from typing import Callable

from flask import current_app
from sqlalchemy import or_, select

from sharewarez import db
from sharewarez.models import BackgroundJob


JobHandler = Callable[["JobContext", dict], dict | None]
_handlers: dict[str, JobHandler] = {}

JOB_DISPLAY_NAMES = {
    'system.noop': 'System check',
    'library.scan': 'Library scan',
    'library.bulk_metadata_refresh': 'Bulk metadata refresh',
    'library.bulk_image_refresh': 'Bulk image refresh',
    'notifications.send_email': 'Send notification email',
    'notifications.send_push': 'Send browser notification',
    'notifications.send_discord': 'Send Discord notification',
    'notifications.send_webhook': 'Send outbound webhook',
    'download.archive.build': 'Prepare resumable download',
}


def job_display_name(task_name):
    return JOB_DISPLAY_NAMES.get(task_name, task_name.replace('.', ' ').replace('_', ' ').title())


class JobCancelled(Exception):
    """Raised cooperatively when cancellation has been requested."""


def register_task(name: str):
    def decorator(handler: JobHandler):
        if name in _handlers:
            raise RuntimeError(f"Background task already registered: {name}")
        _handlers[name] = handler
        return handler
    return decorator


def enqueue(
    task_name, payload=None, *, queue='default', max_attempts=3, created_by_id=None,
    commit=True,
):
    if task_name not in _handlers:
        raise ValueError(f"Unknown background task: {task_name}")
    if not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    job = BackgroundJob(
        task_name=task_name,
        payload=payload or {},
        queue=queue,
        max_attempts=max_attempts,
        created_by_id=created_by_id,
    )
    db.session.add(job)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return job


def cancel_job(job: BackgroundJob):
    """Request cancellation while preserving cooperative worker shutdown."""
    if job.status not in {'queued', 'running'}:
        raise ValueError('Job is not cancellable')
    job.cancel_requested = True
    job.progress_message = 'Cancellation requested'
    if job.status == 'queued':
        job.status = 'cancelled'
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = 'Cancellation requested'
        _mark_archive_job_terminal(job)
    db.session.commit()
    return job


def retry_job(job: BackgroundJob):
    """Reset a terminal job so the worker can claim it again."""
    if job.status not in {'failed', 'cancelled'}:
        raise ValueError('Only failed or cancelled jobs can be retried')
    job.status = 'queued'
    job.cancel_requested = False
    job.attempts = 0
    job.available_at = datetime.now(timezone.utc)
    job.started_at = job.completed_at = job.heartbeat_at = None
    job.locked_by = None
    job.error_message = None
    job.progress = 0
    job.progress_message = 'Retry queued'
    db.session.commit()
    return job


def claim_next(worker_id: str, queue='default'):
    """Atomically claim one runnable job using PostgreSQL row locking."""
    now = datetime.now(timezone.utc)
    job = db.session.execute(
        select(BackgroundJob)
        .where(
            BackgroundJob.queue == queue,
            BackgroundJob.status == 'queued',
            BackgroundJob.available_at <= now,
        )
        .order_by(BackgroundJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        db.session.rollback()
        return None
    job.status = 'running'
    job.attempts += 1
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.locked_by = worker_id
    job.error_message = None
    db.session.commit()
    return job


@dataclass
class JobContext:
    job_id: str
    worker_id: str
    _last_cancel_check: float = field(default=0.0, init=False, repr=False)

    def _job(self, *, refresh=False):
        job = db.session.get(BackgroundJob, self.job_id)
        if job is not None and refresh:
            db.session.refresh(job)
        if job is None or job.locked_by != self.worker_id:
            raise JobCancelled("Job ownership was lost")
        return job

    def heartbeat(self, progress=None, message=None):
        job = self._job(refresh=True)
        if job.cancel_requested:
            raise JobCancelled("Cancellation requested")
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if message is not None:
            job.progress_message = str(message)[:255]
        job.heartbeat_at = datetime.now(timezone.utc)
        db.session.commit()

    def check_cancelled(self, *, force=False):
        now = time.monotonic()
        if not force and now - self._last_cancel_check < 1:
            return
        self._last_cancel_check = now
        job = self._job(refresh=True)
        if job.cancel_requested:
            raise JobCancelled("Cancellation requested")


def execute(job: BackgroundJob, worker_id: str):
    handler = _handlers.get(job.task_name)
    if handler is None:
        _fail_or_retry(job.id, worker_id, f"Unknown background task: {job.task_name}", retry=False)
        return
    context = JobContext(job.id, worker_id)
    try:
        result = handler(context, job.payload or {})
        current = context._job(refresh=True)
        current.status = 'completed'
        current.result = result or {}
        current.progress = 100
        current.completed_at = datetime.now(timezone.utc)
        current.heartbeat_at = current.completed_at
        current.locked_by = None
        db.session.commit()
    except JobCancelled as exc:
        current = db.session.get(BackgroundJob, job.id)
        if current:
            current.status = 'cancelled'
            current.error_message = str(exc)
            current.completed_at = datetime.now(timezone.utc)
            current.locked_by = None
            _mark_archive_job_terminal(current)
            db.session.commit()
    except Exception as exc:
        current_app.logger.exception("Background job %s failed", job.id)
        db.session.rollback()
        _fail_or_retry(job.id, worker_id, str(exc), retry=True)


def _fail_or_retry(job_id, worker_id, message, *, retry):
    job = db.session.get(BackgroundJob, job_id)
    if job is None or job.locked_by != worker_id:
        return
    now = datetime.now(timezone.utc)
    job.error_message = message[:4000]
    job.locked_by = None
    if retry and not job.cancel_requested and job.attempts < job.max_attempts:
        job.status = 'queued'
        job.available_at = now + timedelta(seconds=min(300, 2 ** job.attempts))
        job.progress_message = f"Retry {job.attempts + 1} of {job.max_attempts} scheduled"
        _mark_archive_job_retrying(job)
    else:
        job.status = 'cancelled' if job.cancel_requested else 'failed'
        job.completed_at = now
        _mark_archive_job_terminal(job)
    db.session.commit()


def _mark_archive_job_terminal(job):
    if job.task_name != 'download.archive.build':
        return
    from sharewarez.models import DownloadArchive, DownloadRequest

    archive_id = str((job.payload or {}).get('archive_id') or '')
    archive = db.session.get(DownloadArchive, archive_id) if archive_id else None
    if archive is None:
        return
    archive.state = 'failed'
    archive.build_job_id = None
    if not archive.failure_code:
        archive.failure_code = 'build_cancelled' if job.status == 'cancelled' else 'build_failed'
        archive.failure_message = job.error_message or 'Archive preparation did not complete.'
    db.session.query(DownloadRequest).filter(
        DownloadRequest.archive_id == archive.id,
        DownloadRequest.status == 'processing',
    ).update({'status': 'failed'}, synchronize_session=False)


def _mark_archive_job_retrying(job):
    if job.task_name != 'download.archive.build':
        return
    from sharewarez.models import DownloadArchive

    archive_id = str((job.payload or {}).get('archive_id') or '')
    archive = db.session.get(DownloadArchive, archive_id) if archive_id else None
    if archive is not None:
        archive.state = 'queued'
        archive.build_job_id = job.id


def recover_stale_jobs(stale_after_seconds=120):
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    jobs = db.session.execute(
        select(BackgroundJob).where(
            BackgroundJob.status == 'running',
            or_(BackgroundJob.heartbeat_at.is_(None), BackgroundJob.heartbeat_at < cutoff),
        ).with_for_update(skip_locked=True)
    ).scalars().all()
    for job in jobs:
        job.locked_by = None
        if job.cancel_requested:
            job.status = 'cancelled'
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = 'Cancellation requested'
            _mark_archive_job_terminal(job)
        elif job.attempts < job.max_attempts:
            job.status = 'queued'
            job.available_at = datetime.now(timezone.utc)
            job.progress_message = 'Recovered after worker interruption'
            _mark_archive_job_retrying(job)
        else:
            job.status = 'failed'
            job.error_message = 'Worker stopped before the job completed'
            job.completed_at = datetime.now(timezone.utc)
            _mark_archive_job_terminal(job)
    db.session.commit()
    return len(jobs)


def worker_identity():
    return f"{socket.gethostname()}:{id(db)}"


@register_task('system.noop')
def noop_task(context, payload):
    context.heartbeat(100, 'Completed')
    return {'echo': payload}


@register_task('notifications.send_email')
def send_notification_email_task(context, payload):
    """Deliver a previously rendered transactional email outside the web request."""
    from sharewarez.utils.smtp import send_email

    recipient = str(payload.get('recipient') or '').strip()
    subject = str(payload.get('subject') or '').strip()
    html = str(payload.get('html') or '')
    if not recipient or not subject or not html:
        raise ValueError('Email job payload is incomplete.')
    context.heartbeat(25, 'Connecting to mail server')
    sent = send_email(recipient, subject, html, show_feedback=False)
    context.heartbeat(100, 'Email sent' if sent else 'Email delivery skipped')
    return {'sent': bool(sent)}


@register_task('notifications.send_push')
def send_notification_push_task(context, payload):
    from sharewarez.utils.web_push import send_push_notifications

    context.heartbeat(20, 'Sending browser notification')
    delivered = send_push_notifications(
        payload.get('user_ids') or [], payload.get('title') or '',
        payload.get('message') or '', payload.get('link_url'),
    )
    return {'delivered': delivered}


@register_task('notifications.send_discord')
def send_notification_discord_task(context, payload):
    from discord_webhook import DiscordEmbed, DiscordWebhook
    from sharewarez.models import GlobalSettings, NotificationEvent

    event = db.session.get(NotificationEvent, payload.get('event_id'))
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    if event is None or settings is None or not settings.discord_webhook_url:
        return {'sent': False}
    context.heartbeat(20, 'Sending Discord notification')
    webhook = DiscordWebhook(url=settings.discord_webhook_url, rate_limit_retry=True)
    webhook.add_embed(DiscordEmbed(
        title=event.title, description=event.message,
        url=((settings.site_url or '').rstrip('/') + (event.link_url or '')),
        color='03b2f8',
    ))
    webhook.execute()
    return {'sent': True}


@register_task('notifications.send_webhook')
def send_outbound_webhook_task(context, payload):
    from sharewarez.utils.outbound_webhooks import deliver_webhook

    job = context._job(refresh=True)
    context.heartbeat(20, 'Sending outbound webhook')
    return deliver_webhook(
        payload.get('delivery_id'), final_attempt=job.attempts >= job.max_attempts,
    )


@register_task('download.archive.build')
def build_download_archive_task(context, payload):
    from sharewarez.utils.download_cache import build_archive

    archive_id = str(payload.get('archive_id') or '')
    if not archive_id:
        raise ValueError('Archive job payload is incomplete.')
    return build_archive(context, archive_id)


@register_task('library.scan')
def library_scan_task(context, payload):
    """Run the existing scanner in the persistent worker process."""
    from sharewarez.models import Library
    from sharewarez.utilities import scan_and_add_games
    from sharewarez.utils.incremental_scanning import (
        filesystem_fingerprint, has_changed, save_scan_state,
    )

    library_uuid = payload['library_uuid']
    library = db.session.get(Library, library_uuid)
    if library is None:
        raise ValueError(f"Library not found: {library_uuid}")
    scan_mode = payload.get('scan_mode', 'folders')
    context.heartbeat(1, f"Indexing {library.name}")
    fingerprint, entry_count, total_size = filesystem_fingerprint(payload['folder_path'], context)
    force_scan = any(payload.get(key) for key in (
        'force_updates_extras_scan', 'fetch_hltb', 'force_hltb_refetch',
    ))
    if not force_scan and not has_changed(
        library_uuid, payload['folder_path'], scan_mode, fingerprint,
    ):
        context.heartbeat(99, f"No filesystem changes in {library.name}")
        return {
            'library_uuid': library_uuid, 'folder_path': payload['folder_path'],
            'skipped': True, 'entry_count': entry_count, 'total_size': total_size,
        }

    context.heartbeat(10, f"Scanning changed library {library.name}")
    scan_and_add_games(
        payload['folder_path'],
        scan_mode=scan_mode,
        library_uuid=library_uuid,
        remove_missing=bool(payload.get('remove_missing')),
        download_missing_images=bool(payload.get('download_missing_images')),
        force_updates_extras_scan=bool(payload.get('force_updates_extras_scan')),
        fetch_hltb=bool(payload.get('fetch_hltb')),
        force_hltb_refetch=bool(payload.get('force_hltb_refetch')),
    )
    save_scan_state(
        library_uuid, payload['folder_path'], scan_mode,
        fingerprint, entry_count, total_size,
    )
    context.heartbeat(99, f"Finished scanning {library.name}")
    return {
        'library_uuid': library_uuid, 'folder_path': payload['folder_path'],
        'skipped': False, 'entry_count': entry_count, 'total_size': total_size,
    }


@register_task('library.bulk_metadata_refresh')
def library_bulk_metadata_refresh_task(context, payload):
    """Refresh every game's metadata while reporting aggregate job progress."""
    from sharewarez.models import Game, Library
    from sharewarez.utilities import refresh_game_metadata_and_updates

    library_uuid = payload['library_uuid']
    library = db.session.get(Library, library_uuid)
    if library is None:
        raise ValueError(f'Library not found: {library_uuid}')
    library_name = library.name

    games = db.session.execute(
        select(Game.uuid, Game.name)
        .where(Game.library_uuid == library_uuid)
        .order_by(Game.name)
    ).all()
    total = len(games)
    if total == 0:
        context.heartbeat(99, f'No games found in {library_name}')
        return {
            'library_uuid': library_uuid,
            'library_name': library_name,
            'games_total': 0,
            'games_succeeded': 0,
            'games_failed': 0,
            'failures': [],
        }

    succeeded = 0
    failures: list[dict[str, str]] = []
    for index, (game_uuid, game_name) in enumerate(games, start=1):
        context.check_cancelled()
        context.heartbeat(
            max(1, int(((index - 1) / total) * 98)),
            f'Refreshing {index} of {total}: {game_name}',
        )
        try:
            refresh_game_metadata_and_updates(game_uuid)
            succeeded += 1
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                '[BULK METADATA REFRESH] Error refreshing game %s', game_uuid
            )
            if len(failures) < 50:
                failures.append({
                    'game_uuid': game_uuid,
                    'game_name': game_name,
                    'error': str(exc)[:500],
                })
        finally:
            db.session.remove()

    failed = total - succeeded
    context.heartbeat(
        99,
        f'Finished {library_name}: {succeeded} refreshed, {failed} failed',
    )
    return {
        'library_uuid': library_uuid,
        'library_name': library_name,
        'games_total': total,
        'games_succeeded': succeeded,
        'games_failed': failed,
        'failures': failures,
    }


@register_task('library.bulk_image_refresh')
def library_bulk_image_refresh_task(context, payload):
    """Refresh every game's artwork while reporting aggregate job progress."""
    from sharewarez.models import Game, Library
    from sharewarez.utils.scanning import refresh_images_in_background

    library_uuid = payload['library_uuid']
    library = db.session.get(Library, library_uuid)
    if library is None:
        raise ValueError(f'Library not found: {library_uuid}')
    library_name = library.name
    games = db.session.execute(
        select(Game.uuid, Game.name)
        .where(Game.library_uuid == library_uuid)
        .order_by(Game.name)
    ).all()
    total = len(games)
    succeeded = 0
    failures: list[dict[str, str]] = []

    for index, (game_uuid, game_name) in enumerate(games, start=1):
        context.check_cancelled()
        context.heartbeat(
            max(1, int(((index - 1) / max(total, 1)) * 98)),
            f'Refreshing images {index} of {total}: {game_name}',
        )
        try:
            refresh_result = refresh_images_in_background(game_uuid)
            if isinstance(refresh_result, tuple):
                refresh_succeeded, refresh_error = refresh_result
            else:
                refresh_succeeded, refresh_error = bool(refresh_result), None
            if refresh_succeeded:
                succeeded += 1
            elif len(failures) < 50:
                failures.append({
                    'game_uuid': game_uuid,
                    'game_name': game_name,
                    'error': refresh_error or 'Image refresh did not complete',
                })
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                '[BULK IMAGE REFRESH] Error refreshing game %s', game_uuid
            )
            if len(failures) < 50:
                failures.append({
                    'game_uuid': game_uuid,
                    'game_name': game_name,
                    'error': str(exc)[:500],
                })
        finally:
            db.session.remove()

    failed = total - succeeded
    context.heartbeat(
        99,
        f'Finished {library_name}: {succeeded} refreshed, {failed} failed',
    )
    return {
        'library_uuid': library_uuid,
        'library_name': library_name,
        'games_total': total,
        'games_succeeded': succeeded,
        'games_failed': failed,
        'failures': failures,
    }
