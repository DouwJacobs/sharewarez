from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sharewarez.models import Notification, User
from sharewarez.utils.notifications import create_notifications


@pytest.fixture
def user(db_session):
    suffix = uuid4().hex[:8]
    record = User(name=f'user_{suffix}', email=f'user_{suffix}@example.com', password_hash='hash', role='user')
    db_session.add(record)
    db_session.commit()
    return record


@pytest.fixture
def admin_user(db_session):
    suffix = uuid4().hex[:8]
    record = User(name=f'admin_{suffix}', email=f'admin_{suffix}@example.com', password_hash='hash', role='admin')
    db_session.add(record)
    db_session.commit()
    return record


def test_notification_delivery_is_idempotent(db_session, user):
    assert create_notifications(
        [user.id], 'new_game', 'New game', 'A game arrived.',
        '/game_details/game-uuid', 'new-game:game-uuid',
    ) == 1
    assert create_notifications(
        [user.id], 'new_game', 'New game', 'A game arrived.',
        '/game_details/game-uuid', 'new-game:game-uuid',
    ) == 0

    assert db_session.query(Notification).filter_by(user_id=user.id).count() == 1


def test_notification_center_is_user_scoped(client, db_session, user, admin_user):
    db_session.add_all([
        Notification(user_id=user.id, event_type='new_game', title='Mine', message='Visible'),
        Notification(user_id=admin_user.id, event_type='new_game', title='Theirs', message='Hidden'),
    ])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True

    response = client.get('/notifications')

    assert response.status_code == 200
    assert b'Mine' in response.data
    assert b'Theirs' not in response.data


def test_mark_all_read_only_updates_current_user(client, db_session, user, admin_user):
    mine = Notification(user_id=user.id, event_type='new_game', title='Mine', message='Visible')
    theirs = Notification(user_id=admin_user.id, event_type='new_game', title='Theirs', message='Hidden')
    db_session.add_all([mine, theirs])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True

    response = client.post('/notifications/read-all', data={'csrf_token': 'test_token'})

    assert response.status_code == 302
    db_session.refresh(mine)
    db_session.refresh(theirs)
    assert isinstance(mine.read_at, datetime)
    assert mine.read_at.tzinfo is not None or mine.read_at.replace(tzinfo=timezone.utc)
    assert theirs.read_at is None
