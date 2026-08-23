"""Administrator notifications for notable download activity."""

from sqlalchemy import func, select

from sharewarez import db
from sharewarez.models import DownloadRequest, DownloadTransfer, GlobalSettings
from sharewarez.utils.notifications import active_user_ids, create_notifications


def _enabled(key):
    record = db.session.execute(select(GlobalSettings)).scalars().first()
    return bool(record and (record.settings or {}).get(key, False))


def notify_admin_download_cancelled(download_request, user_name):
    if not _enabled('notifyAdminDownloadCancellations'):
        return 0
    title = download_request.content_title or download_request.game.name
    return create_notifications(
        active_user_ids(role='admin'),
        'download_cancelled',
        f'Download cancelled: {title}',
        f'{user_name} cancelled download request {download_request.id}.',
        link_url='/admin/manage-downloads',
        dedupe_key=f'download-cancelled:{download_request.id}',
    )


def notify_admin_repeat_download(transfer):
    if not transfer.download_request_id or not _enabled('notifyAdminRepeatDownloads'):
        return 0
    attempt = db.session.execute(
        select(func.count(DownloadTransfer.id)).where(
            DownloadTransfer.user_id == transfer.user_id,
            DownloadTransfer.download_request_id == transfer.download_request_id,
        )
    ).scalar_one()
    if attempt < 2:
        return 0
    request = db.session.get(DownloadRequest, transfer.download_request_id)
    title = (request.content_title if request else None) or transfer.filename
    user_name = transfer.user.name
    return create_notifications(
        active_user_ids(role='admin'),
        'download_repeated',
        f'Repeated download: {title}',
        f'{user_name} started download attempt {attempt} for the same request.',
        link_url='/admin/manage-downloads',
        dedupe_key=f'download-repeat:{transfer.download_request_id}:{attempt}',
    )
