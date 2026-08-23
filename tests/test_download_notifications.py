from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sharewarez.utils.download_notifications import (
    notify_admin_download_cancelled,
    notify_admin_repeat_download,
)


@patch('sharewarez.utils.download_notifications.create_notifications')
@patch('sharewarez.utils.download_notifications.active_user_ids', return_value=[1, 2])
@patch('sharewarez.utils.download_notifications._enabled', return_value=True)
def test_cancelled_download_notifies_admins(_enabled, _admins, create):
    request = SimpleNamespace(
        id=42,
        content_title='Example Game',
        game=SimpleNamespace(name='Example Game'),
    )

    notify_admin_download_cancelled(request, 'Alice')

    create.assert_called_once_with(
        [1, 2], 'download_cancelled', 'Download cancelled: Example Game',
        'Alice cancelled download request 42.',
        link_url='/admin/manage-downloads',
        dedupe_key='download-cancelled:42',
    )


@patch('sharewarez.utils.download_notifications.create_notifications')
@patch('sharewarez.utils.download_notifications.active_user_ids', return_value=[1])
@patch('sharewarez.utils.download_notifications._enabled', return_value=True)
@patch('sharewarez.utils.download_notifications.db')
def test_second_transfer_notifies_admin(db, _enabled, _admins, create):
    db.session.execute.return_value.scalar_one.return_value = 2
    db.session.get.return_value = SimpleNamespace(content_title='Example Game')
    transfer = SimpleNamespace(
        user_id=7,
        download_request_id=42,
        filename='example.zip',
        user=SimpleNamespace(name='Alice'),
    )

    notify_admin_repeat_download(transfer)

    create.assert_called_once_with(
        [1], 'download_repeated', 'Repeated download: Example Game',
        'Alice started download attempt 2 for the same request.',
        link_url='/admin/manage-downloads',
        dedupe_key='download-repeat:42:2',
    )


@patch('sharewarez.utils.download_notifications.create_notifications', MagicMock())
@patch('sharewarez.utils.download_notifications._enabled', return_value=False)
def test_download_notifications_are_opt_in(_enabled):
    request = SimpleNamespace(id=42, content_title='Example Game')
    assert notify_admin_download_cancelled(request, 'Alice') == 0
