from datetime import date
from uuid import uuid4

from sharewarez.models import DiscoverySection, User, UserPreference
from sharewarez.utils.notifications import create_notifications
from sharewarez.utils.formatting import friendly_date, game_monogram
from sharewarez.utils.user_preferences import get_experience_settings


def _user(db_session):
    suffix = uuid4().hex[:10]
    user = User(
        name=f'experience_{suffix}', email=f'experience_{suffix}@example.com',
        password_hash='hash', role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_experience_settings_are_default_filled(db_session):
    user = _user(db_session)
    user.preferences = UserPreference(
        user_id=user.id,
        experience_settings={'library_view': 'list', 'notifications': {'issues': False}},
    )
    db_session.commit()

    settings = get_experience_settings(user)

    assert settings['library_view'] == 'list'
    assert settings['notifications']['issues'] is False
    assert settings['notifications']['requests'] is True
    assert settings['saved_library_views'] == []


def test_disabled_notification_category_skips_delivery(db_session):
    user = _user(db_session)
    user.preferences = UserPreference(
        user_id=user.id,
        experience_settings={'notifications': {'downloads': False}},
    )
    db_session.commit()

    created = create_notifications(
        [user.id], 'download_cancelled', 'Cancelled', 'A download was cancelled.',
        commit=False,
    )

    assert created == 0


def test_library_view_and_saved_view_are_account_scoped(client, db_session):
    user = _user(db_session)
    _login(client, user)

    response = client.post('/api/preferences/library', json={
        'action': 'set_view', 'view': 'compact',
    })
    assert response.status_code == 200
    response = client.post('/api/preferences/library', json={
        'action': 'save_view', 'name': 'Indie favourites',
        'query': '?genre=Indie&sort_by=rating&unsafe=discarded',
    })
    assert response.status_code == 200

    db_session.refresh(user.preferences)
    settings = get_experience_settings(user)
    assert settings['library_view'] == 'compact'
    assert settings['saved_library_views'] == [{
        'name': 'Indie favourites', 'query': 'genre=Indie&sort_by=rating',
    }]


def test_discover_visibility_and_order_are_saved(client, db_session):
    user = _user(db_session)
    identifiers = [f'latest_{uuid4().hex[:6]}', f'rated_{uuid4().hex[:6]}']
    db_session.add_all([
        DiscoverySection(name='Latest test', identifier=identifiers[0], is_visible=True),
        DiscoverySection(name='Rated test', identifier=identifiers[1], is_visible=True),
    ])
    db_session.commit()
    _login(client, user)

    response = client.post('/api/preferences/discover', json={
        'order': identifiers[::-1], 'hidden': [identifiers[0]],
    })

    assert response.status_code == 200
    db_session.refresh(user.preferences)
    settings = get_experience_settings(user)
    assert settings['discover_section_order'] == identifiers[::-1]
    assert settings['discover_hidden_sections'] == [identifiers[0]]

    db_session.query(DiscoverySection).filter(
        DiscoverySection.identifier.in_(identifiers)
    ).delete(synchronize_session=False)
    db_session.commit()


def test_friendly_date_formats_database_and_iso_values_consistently():
    assert friendly_date(date(2026, 7, 9)) == '9 Jul 2026'
    assert friendly_date('2026-07-09') == '9 Jul 2026'
    assert friendly_date(None) == 'Not available'


def test_game_monogram_uses_meaningful_title_words():
    assert game_monogram('God of War Ragnarök') == 'GWR'
    assert game_monogram("Assassin's Creed") == 'AC'
    assert game_monogram('Bellwright') == 'B'
    assert game_monogram(None) == '?'
