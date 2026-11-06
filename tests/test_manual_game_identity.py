from contextlib import nullcontext
from uuid import uuid4
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import Game, Library, SystemEvents, User
from sharewarez.platform import LibraryPlatform


@pytest.fixture
def admin_user(db_session):
    user = User(
        name=f'manual_identity_admin_{uuid4().hex[:8]}',
        email=f'manual-{uuid4().hex[:8]}@example.com',
        password_hash='hashed',
        role='admin',
        user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def game_library(db_session):
    library = Library(
        name=f'Manual identity {uuid4().hex[:8]}',
        image_url='/static/library_test.jpg',
        platform=LibraryPlatform.PCWIN,
        display_order=1,
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.mark.parametrize("real_thread", [False, True])
def test_manual_game_uses_local_identity_without_fake_igdb_id(
    client, db_session, admin_user, game_library, monkeypatch, real_thread,
):
    with client.session_transaction() as session:
        session['_user_id'] = str(admin_user.id)
        session['_fresh'] = True

    form_data = {
        'library_uuid': str(game_library.uuid),
        'manual_identity': '1',
        'igdb_id': '',
        'name': 'Locally identified game',
        'full_disk_path': '/games/locally-identified-game',
        'status': 'RELEASED',
        'category': 'MAIN_GAME',
    }
    from flask import has_request_context
    from threading import Thread
    observations = []
    parent_session = db_session()
    def refresh(game_uuid):
        observations.append((has_request_context(), db_session() is parent_session,
                             db_session.scalar(select(Game).where(Game.uuid == game_uuid)) is not None))
    def start_and_join(thread):
        original_start(thread)
        thread.join(timeout=5)
        assert not thread.is_alive()
    original_start = Thread.start
    if real_thread:
        monkeypatch.setattr('sharewarez.routes_games_ext.add.refresh_images_in_background', refresh)
        monkeypatch.setattr(Thread, 'start', start_and_join)
    with (
        patch('sharewarez.routes_games_ext.add.is_scan_job_running', return_value=False),
        patch('sharewarez.routes_games_ext.add.get_allowed_base_directories', return_value=['/games']),
        patch('sharewarez.routes_games_ext.add.is_safe_path', return_value=(True, None)),
        patch('sharewarez.routes_games_ext.add.read_first_nfo_content', return_value=None),
        patch('sharewarez.routes_games_ext.add.Thread.start') if not real_thread else nullcontext(),
    ):
        response = client.post('/add_game_manual', data=form_data)

    error_summary = BeautifulSoup(
        response.get_data(as_text=True), 'html.parser'
    ).select_one('.game-edit-error-summary')
    response_html = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    failure_text = (
        error_summary.get_text(' ', strip=True) if error_summary
        else ' | '.join(
            node.get_text(' ', strip=True)
            for node in response_html.select('.sw-toast-body')
        )
    )
    if response.status_code != 302:
        event = db_session.execute(
            select(SystemEvents).order_by(SystemEvents.id.desc()).limit(1)
        ).scalar_one_or_none()
        if event is not None:
            failure_text = f'{failure_text} | {event.event_text}'
    assert response.status_code == 302, failure_text
    game = db_session.execute(
        select(Game).filter_by(name='Locally identified game', library_uuid=game_library.uuid)
    ).scalar_one()
    assert game.igdb_id is None
    assert len(game.external_identities) == 1
    identity = game.external_identities[0]
    assert identity.provider == 'local'
    assert identity.external_id == game.uuid
    assert identity.canonical is True

    if real_thread:
        assert observations == [(False, False, True)]
