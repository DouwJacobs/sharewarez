from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from sharewarez.models import (
    Game,
    GameIssue,
    GameIssueComment,
    GameRequest,
    GameRequestUser,
    GlobalSettings,
    Library,
    Notification,
    User,
)
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.issue_notifications import notify_issue_comment, notify_issue_created


@pytest.fixture
def issue_records(db_session):
    suffix = uuid4().hex[:8]
    library = Library(name=f'Issue Library {suffix}', platform=LibraryPlatform.PCWIN)
    reporter = User(
        name=f'issue_user_{suffix}', email=f'issue_user_{suffix}@example.com',
        password_hash='not-used', role='user', state=True,
    )
    other_user = User(
        name=f'issue_other_{suffix}', email=f'issue_other_{suffix}@example.com',
        password_hash='not-used', role='user', state=True,
    )
    admin = User(
        name=f'issue_admin_{suffix}', email=f'issue_admin_{suffix}@example.com',
        password_hash='not-used', role='admin', state=True,
    )
    db_session.add_all([library, reporter, other_user, admin])
    db_session.flush()
    game = Game(
        uuid=str(uuid4()), name=f'Issue Game {suffix}',
        library_uuid=library.uuid, size=1,
    )
    db_session.add(game)
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db_session.add(settings)
    values = dict(settings.settings or {})
    values.update({
        'enableGameIssues': True,
        'notifyAdminIssueEmail': False,
        'notifyReporterIssueEmail': False,
    })
    settings.settings = values
    db_session.commit()
    return {
        'library': library, 'game': game, 'reporter': reporter,
        'other_user': other_user, 'admin': admin,
    }


def login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def make_issue(db_session, records, **overrides):
    values = {
        'game_uuid': records['game'].uuid,
        'reporter_id': records['reporter'].id,
        'category': 'launch_problem',
        'title': 'Installer exits before completing',
        'description': 'The installer exits at eighty percent without an error message.',
    }
    values.update(overrides)
    issue = GameIssue(**values)
    db_session.add(issue)
    db_session.commit()
    return issue


@patch('sharewarez.routes_issues.notify_issue_created')
def test_user_can_create_issue_for_existing_game(mock_notify, client, db_session, issue_records):
    login(client, issue_records['reporter'])

    response = client.post(
        f"/game_details/{issue_records['game'].uuid}/issues",
        json={
            'category': 'broken_download',
            'title': 'Archive checksum does not match',
            'description': 'The archive fails its checksum after downloading it twice.',
        },
    )

    assert response.status_code == 201
    issue = db_session.get(GameIssue, response.get_json()['issue_id'])
    assert issue.reporter_id == issue_records['reporter'].id
    assert issue.game_uuid == issue_records['game'].uuid
    assert issue.status == 'open'
    mock_notify.assert_called_once_with(issue)


def test_issue_creation_validates_payload(client, issue_records):
    login(client, issue_records['reporter'])
    response = client.post(
        f"/game_details/{issue_records['game'].uuid}/issues",
        json={'category': 'invalid', 'title': 'Bad', 'description': 'Too short'},
    )
    assert response.status_code == 400
    assert 'valid issue category' in response.get_json()['error']


def test_reporter_can_read_issue_detail(client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    login(client, issue_records['reporter'])
    response = client.get(f'/issues/{issue.id}')
    assert response.status_code == 200
    assert issue.title.encode() in response.data


def test_issue_detail_is_hidden_from_other_users(client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    login(client, issue_records['other_user'])
    assert client.get(f'/issues/{issue.id}').status_code == 404


@patch('sharewarez.routes_issues.notify_issue_comment')
def test_reporter_can_comment(mock_notify, client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    issue.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.commit()
    login(client, issue_records['reporter'])
    response = client.post(f'/issues/{issue.id}/comments', data={'body': 'More details from the reporter.'})
    assert response.status_code == 302
    comment = db_session.query(GameIssueComment).filter_by(issue_id=issue.id).one()
    assert comment.body == 'More details from the reporter.'
    assert issue.updated_at.year > 2020
    mock_notify.assert_called_once_with(issue, comment)


@patch('sharewarez.routes_issues.notify_issue_comment')
def test_admin_can_comment(mock_notify, client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    login(client, issue_records['admin'])
    response = client.post(
        f'/admin/issues/{issue.id}/comments',
        data={'body': 'Please try the replacement archive.'},
    )
    assert response.status_code == 302
    comment = db_session.query(GameIssueComment).filter_by(issue_id=issue.id).one()
    assert comment.body == 'Please try the replacement archive.'
    mock_notify.assert_called_once_with(issue, comment)


@patch('sharewarez.routes_issues.notify_issue_comment')
def test_admin_internal_note_is_stored_as_private(mock_notify, client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    login(client, issue_records['admin'])
    response = client.post(
        f'/admin/issues/{issue.id}/comments',
        data={'body': 'Storage node needs repair.', 'is_internal': 'on'},
    )
    assert response.status_code == 302
    comment = db_session.query(GameIssueComment).filter_by(issue_id=issue.id).one()
    assert comment.is_internal is True

    login(client, issue_records['reporter'])
    response = client.get(f'/issues/{issue.id}')
    assert b'Storage node needs repair.' not in response.data
    mock_notify.assert_called_once_with(issue, comment)


@patch('sharewarez.routes_issues.notify_issue_status')
def test_admin_status_update_creates_timeline_activity(mock_notify, client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    login(client, issue_records['admin'])
    response = client.post(
        f'/admin/issues/{issue.id}/update',
        data={
            'status': 'in_progress',
            'category': issue.category,
            'title': issue.title,
            'description': issue.description,
        },
    )
    assert response.status_code == 302
    db_session.refresh(issue)
    assert issue.status == 'in_progress'
    assert issue.handled_by_user_id == issue_records['admin'].id
    activity = db_session.query(GameIssueComment).filter_by(issue_id=issue.id, kind='status').one()
    assert 'Open to In progress' in activity.body
    mock_notify.assert_called_once_with(issue, 'open', activity)


@patch('sharewarez.routes_issues.notify_issue_status')
def test_reporter_can_close_and_reopen_issue(mock_notify, client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    login(client, issue_records['reporter'])
    assert client.post(f'/issues/{issue.id}/close').status_code == 302
    db_session.refresh(issue)
    assert issue.status == 'closed'
    assert issue.resolved_at is not None
    assert client.post(f'/issues/{issue.id}/reopen').status_code == 302
    db_session.refresh(issue)
    assert issue.status == 'open'
    assert issue.resolved_at is None
    assert mock_notify.call_count == 2


def test_admin_list_groups_multiple_issues_for_one_game(client, db_session, issue_records):
    first = make_issue(db_session, issue_records)
    second = make_issue(
        db_session, issue_records,
        title='Missing language pack',
        description='The optional language pack is absent from the download.',
        category='missing_files',
    )
    login(client, issue_records['admin'])
    response = client.get('/admin/issues?status=open')
    assert response.status_code == 200
    assert first.title.encode() in response.data
    assert second.title.encode() in response.data
    assert b'2 issues in this view' not in response.data
    assert b'<strong>2</strong> open' in response.data

    filtered = client.get('/admin/issues?status=all&category=missing_files&q=language')
    assert filtered.status_code == 200
    assert second.title.encode() in filtered.data
    assert first.title.encode() not in filtered.data


def test_legacy_issue_records_are_excluded_from_game_requests(client, db_session, issue_records):
    legacy = GameRequest(
        request_type='issue', game_name='Legacy issue hidden from requests',
        source_game_uuid=issue_records['game'].uuid, issue_category='other',
    )
    legacy.requesters.append(GameRequestUser(user_id=issue_records['reporter'].id, requester_note='Legacy'))
    db_session.add(legacy)
    db_session.commit()
    login(client, issue_records['admin'])
    response = client.get('/admin/game-requests?status=all')
    assert response.status_code == 200
    assert b'Legacy issue hidden from requests' not in response.data


@patch('sharewarez.routes_issues.notify_issue_deleted')
def test_admin_can_delete_issue_and_comments(mock_notify, client, db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    comment = GameIssueComment(issue_id=issue.id, author_id=issue_records['reporter'].id, body='Follow-up')
    db_session.add(comment)
    db_session.commit()
    issue_id = issue.id
    login(client, issue_records['admin'])
    response = client.post(f'/admin/issues/{issue_id}/delete')
    assert response.status_code == 302
    assert db_session.get(GameIssue, issue_id) is None
    assert db_session.query(GameIssueComment).filter_by(issue_id=issue_id).count() == 0
    mock_notify.assert_called_once()


def test_issue_notifications_reach_admin_and_reporter(db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    notify_issue_created(issue)
    admin_notification = db_session.query(Notification).filter_by(
        user_id=issue_records['admin'].id,
        event_type='issue_created',
    ).one()
    assert admin_notification.link_url == f'/admin/issues/{issue.id}'

    admin_comment = GameIssueComment(
        issue_id=issue.id,
        author_id=issue_records['admin'].id,
        body='We are investigating this now.',
    )
    db_session.add(admin_comment)
    db_session.commit()
    notify_issue_comment(issue, admin_comment)
    reporter_notification = db_session.query(Notification).filter_by(
        user_id=issue_records['reporter'].id,
        event_type='issue_comment',
    ).one()
    assert reporter_notification.link_url == f'/issues/{issue.id}'


def test_internal_issue_comment_does_not_notify_reporter(db_session, issue_records):
    issue = make_issue(db_session, issue_records)
    comment = GameIssueComment(
        issue_id=issue.id,
        author_id=issue_records['admin'].id,
        body='Private diagnostic note.',
        is_internal=True,
    )
    db_session.add(comment)
    db_session.commit()
    notify_issue_comment(issue, comment)
    assert db_session.query(Notification).filter_by(
        user_id=issue_records['reporter'].id,
        event_type='issue_comment',
        dedupe_key=f'issue:{issue.id}:comment:{comment.id}',
    ).count() == 0


@patch('sharewarez.utils.notification_events.enqueue')
def test_enabled_issue_email_is_queued(mock_enqueue, db_session, issue_records):
    settings = db_session.query(GlobalSettings).first()
    values = dict(settings.settings or {})
    values['notifyAdminIssueEmail'] = True
    settings.settings = values
    db_session.commit()
    issue = make_issue(db_session, issue_records)

    notify_issue_created(issue)

    matching_calls = [
        call for call in mock_enqueue.call_args_list
        if call.args[0] == 'notifications.send_email'
        and call.args[1]['recipient'] == issue_records['admin'].email
    ]
    assert len(matching_calls) == 1
    assert matching_calls[0].kwargs['max_attempts'] == 3
    assert matching_calls[0].kwargs['commit'] is False
