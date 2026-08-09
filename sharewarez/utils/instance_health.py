from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from sharewarez import db
from sharewarez.models import BackgroundJob, GlobalSettings


def _integration(name, configured, enabled=True, last_tested=None, settings_url='/admin/integrations', test_required=True):
    if not enabled:
        return {'name': name, 'status': 'disabled', 'message': 'Disabled', 'last_tested': None, 'settings_url': settings_url}
    if not configured:
        return {'name': name, 'status': 'warning', 'message': 'Configuration incomplete', 'last_tested': None, 'settings_url': settings_url}
    return {
        'name': name,
        'status': 'healthy' if last_tested or not test_required else 'warning',
        'message': 'Configured and tested' if last_tested else 'Configured' if not test_required else 'Configured; test recommended',
        'last_tested': last_tested,
        'settings_url': settings_url,
    }


def get_instance_diagnostics():
    """Aggregate safe, non-secret instance diagnostics without outbound requests."""
    db.session.execute(text('SELECT 1'))
    settings = db.session.execute(select(GlobalSettings).limit(1)).scalar_one_or_none()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    stale_jobs = db.session.execute(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.status == 'running',
            BackgroundJob.heartbeat_at < cutoff,
        )
    ).scalar_one()

    integrations = [
        _integration(
            'SMTP',
            bool(settings and settings.smtp_server and settings.smtp_port and settings.smtp_default_sender),
            bool(settings and settings.smtp_enabled),
            settings.smtp_last_tested if settings else None, settings_url='/admin/integrations#email',
        ),
        _integration(
            'Discord', bool(settings and settings.discord_webhook_url),
            last_tested=None, settings_url='/admin/integrations#discord', test_required=False,
        ),
        _integration(
            'IGDB', bool(settings and settings.igdb_client_id and settings.igdb_client_secret),
            last_tested=settings.igdb_last_tested if settings else None,
            settings_url='/admin/integrations#igdb',
        ),
    ]
    return {
        'overall': 'warning' if stale_jobs or any(x['status'] == 'warning' for x in integrations) else 'healthy',
        'database': {'status': 'healthy', 'message': 'Database query succeeded'},
        'jobs': {
            'status': 'warning' if stale_jobs else 'healthy',
            'message': f'{stale_jobs} stale running job(s)' if stale_jobs else 'No stale running jobs',
        },
        'integrations': integrations,
        'checked_at': datetime.now(timezone.utc),
    }
