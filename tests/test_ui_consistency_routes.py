from uuid import uuid4

from sharewarez.models import Game, Library, User, Genre, user_game_status
from sharewarez.platform import LibraryPlatform


def make_fixture(db_session):
    suffix = uuid4().hex
    user = User(name=f'UI {suffix}', email=f'{suffix}@example.test',
                password_hash='test-only', role='user', state=True, is_email_verified=True)
    library = Library(name=f'UI {suffix}', platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library])
    db_session.flush()
    game = Game(name='Shared <card>', library_uuid=library.uuid)
    db_session.add(game)
    db_session.flush()
    return user, game


def sign_in(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_favorites_shared_card_has_fallback_actions_and_play_state(client, db_session):
    user, game = make_fixture(db_session)
    user.favorites.append(game)
    db_session.execute(user_game_status.insert().values(
        user_id=user.id, game_uuid=game.uuid, status='beaten'))
    db_session.commit()
    sign_in(client, user)
    response = client.get('/favorites')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Shared &lt;card&gt;' in html
    assert 'game-cover-placeholder' in html
    assert f'id="menuButton-{game.uuid}"' in html
    assert 'data-current-status="beaten"' in html
    assert 'removeFavoriteModal' not in html
    assert 'discovery-favorites-container' not in html


def test_random_trailer_handles_json_metadata_and_duplicate_genre_matches(client, db_session):
    user, game = make_fixture(db_session)
    game.video_urls = 'https://www.youtube.com/watch?v=example'
    game.metadata_provenance = {'name': 'manual'}
    genres = [Genre(name=f'UI-{uuid4().hex}') for _ in range(2)]
    game.genres.extend(genres)
    db_session.commit()
    sign_in(client, user)
    response = client.get('/api/trailers/random', query_string={
        'library_uuid': game.library_uuid,
        'genres': ','.join(str(genre.id) for genre in genres),
    })
    assert response.status_code == 200
    assert response.json['game_uuid'] == game.uuid
    assert response.json['has_videos'] is True
