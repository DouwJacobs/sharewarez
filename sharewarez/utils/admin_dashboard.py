"""Read-only aggregate data for the administrator overview."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import url_for
from sqlalchemy import func, select

from sharewarez import db
from sharewarez.models import (
    BackgroundJob,
    DownloadRequest,
    DownloadTransfer,
    GameIssue,
    GameRequest,
    LibraryScanState,
    SystemEvents,
)
from sharewarez.utils.instance_health import get_instance_diagnostics


OPEN_ISSUE_STATUSES = ('open', 'in_progress', 'waiting_on_user')
OPEN_REQUEST_STATUSES = ('pending', 'reviewing')


def _count(model, *criteria):
    return db.session.execute(
        select(func.count(model.id)).where(*criteria)
    ).scalar_one()


def _attention_item(kind, title, detail, url, created_at, icon, tone='neutral'):
    return {
        'kind': kind,
        'title': title,
        'detail': detail,
        'url': url,
        'created_at': created_at,
        'icon': icon,
        'tone': tone,
    }


def get_admin_dashboard_context():
    pending_requests = _count(
        GameRequest,
        GameRequest.status.in_(OPEN_REQUEST_STATUSES),
        GameRequest.request_type != 'issue',
    )
    open_issues = _count(GameIssue, GameIssue.status.in_(OPEN_ISSUE_STATUSES))
    active_transfers = _count(DownloadTransfer, DownloadTransfer.status == 'active')
    queued_jobs = _count(BackgroundJob, BackgroundJob.status == 'queued')
    failed_jobs = _count(BackgroundJob, BackgroundJob.status == 'failed')

    event_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    warning_events = _count(
        SystemEvents,
        SystemEvents.timestamp >= event_cutoff,
        SystemEvents.event_level.in_(('warning', 'error', 'critical')),
    )

    metrics = (
        {
            'label': 'Requests', 'value': pending_requests,
            'detail': 'awaiting review', 'icon': 'fa-paper-plane',
            'url': url_for('game_requests.admin_requests', status='all'),
            'tone': 'warning' if pending_requests else 'success',
        },
        {
            'label': 'Issues', 'value': open_issues,
            'detail': 'open reports', 'icon': 'fa-bug',
            'url': url_for('issues.admin_issues', status='open'),
            'tone': 'warning' if open_issues else 'success',
        },
        {
            'label': 'Transfers', 'value': active_transfers,
            'detail': 'active now', 'icon': 'fa-download',
            'url': url_for('download.manage_downloads'),
            'tone': 'primary' if active_transfers else 'neutral',
        },
        {
            'label': 'Jobs', 'value': queued_jobs,
            'detail': 'queued', 'icon': 'fa-list-check',
            'url': url_for('admin2.background_jobs', status='queued'),
            'tone': 'danger' if failed_jobs else 'warning' if queued_jobs else 'success',
            'secondary': f'{failed_jobs} failed' if failed_jobs else None,
        },
        {
            'label': 'System', 'value': warning_events,
            'detail': 'alerts in 24h', 'icon': 'fa-heart-pulse',
            'url': url_for('admin2.system_logs', event_level='warning'),
            'tone': 'danger' if warning_events else 'success',
        },
    )

    attention = []
    request_rows = db.session.execute(
        select(GameRequest).where(
            GameRequest.status.in_(OPEN_REQUEST_STATUSES),
            GameRequest.request_type != 'issue',
        ).order_by(GameRequest.updated_at.desc()).limit(4)
    ).scalars().all()
    for record in request_rows:
        attention.append(_attention_item(
            'Game request', record.game_name,
            record.status.replace('_', ' ').title(),
            url_for('game_requests.admin_request_details', request_id=record.id),
            record.updated_at, 'fa-paper-plane', 'warning',
        ))

    issue_rows = db.session.execute(
        select(GameIssue).where(
            GameIssue.status.in_(OPEN_ISSUE_STATUSES)
        ).order_by(GameIssue.updated_at.desc()).limit(4)
    ).scalars().all()
    for issue in issue_rows:
        attention.append(_attention_item(
            'Game issue', issue.title,
            issue.status.replace('_', ' ').title(),
            url_for('issues.admin_issue_detail', issue_id=issue.id),
            issue.updated_at, 'fa-bug', 'warning',
        ))

    recent_download_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    failed_downloads = db.session.execute(
        select(DownloadRequest).where(
            DownloadRequest.status.in_(('failed', 'cancelled')),
            DownloadRequest.request_time >= recent_download_cutoff,
        ).order_by(DownloadRequest.request_time.desc()).limit(3)
    ).scalars().all()
    for download in failed_downloads:
        content_name = download.content_title or (download.game.name if download.game else 'Download request')
        attention.append(_attention_item(
            'Download', content_name,
            download.status.title(),
            url_for('download.manage_downloads', status=download.status),
            download.request_time, 'fa-download', 'danger',
        ))

    failed_job_rows = db.session.execute(
        select(BackgroundJob).where(
            BackgroundJob.status == 'failed'
        ).order_by(BackgroundJob.completed_at.desc().nullslast(), BackgroundJob.created_at.desc()).limit(3)
    ).scalars().all()
    for job in failed_job_rows:
        attention.append(_attention_item(
            'Background job', job.task_name.replace('.', ' ').replace('_', ' ').title(),
            'Failed', url_for('admin2.background_jobs', status='failed'),
            job.completed_at or job.created_at, 'fa-triangle-exclamation', 'danger',
        ))

    attention.sort(
        key=lambda item: item['created_at'].replace(tzinfo=timezone.utc)
        if item['created_at'] and item['created_at'].tzinfo is None else item['created_at'] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    diagnostics = get_instance_diagnostics()
    last_scan = db.session.execute(select(func.max(LibraryScanState.scanned_at))).scalar_one()
    health_items = [
        {
            'name': 'Database', 'icon': 'fa-database',
            'status': diagnostics['database']['status'],
            'message': diagnostics['database']['message'],
            'url': url_for('info.server_status'),
        },
        {
            'name': 'Job worker', 'icon': 'fa-gears',
            'status': diagnostics['jobs']['status'],
            'message': diagnostics['jobs']['message'],
            'url': url_for('admin2.background_jobs'),
        },
        *(
            {
                'name': item['name'], 'icon': {
                    'SMTP': 'fa-envelope', 'Discord': 'fa-comments', 'IGDB': 'fa-gamepad',
                }.get(item['name'], 'fa-plug'),
                'status': item['status'], 'message': item['message'], 'url': item['settings_url'],
            }
            for item in diagnostics['integrations']
        ),
        {
            'name': 'Library scan', 'icon': 'fa-magnifying-glass',
            'status': 'healthy' if last_scan else 'warning',
            'message': f'Last completed {last_scan.strftime("%Y-%m-%d %H:%M")}' if last_scan else 'No completed scan recorded',
            'url': url_for('main.admin_scan_management'),
        },
    ]

    return {
        'dashboard_metrics': metrics,
        'dashboard_attention': attention[:8],
        'dashboard_health': health_items,
        'dashboard_overall_health': diagnostics['overall'],
        'pending_request_count': pending_requests,
        'open_issue_count': open_issues,
    }
