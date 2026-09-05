import json
from html.parser import HTMLParser
from uuid import uuid4
from urllib.parse import quote
from time import perf_counter
import pytest
from sharewarez.models import User, Game, Library, Genre
from sharewarez.platform import LibraryPlatform


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.fixture
def catalogue(client, db_session):
    user = User(name=uuid4().hex, email=uuid4().hex+'@example.com', role='admin', state=True, password_hash='unused')
    library = Library(name='Named library', platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library]); db_session.flush()
    game = Game(name='Unrated game', library_uuid=library.uuid, rating=None)
    db_session.add(game); db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    return library, game


@pytest.mark.parametrize('value', [[], [1], None, 12, {'rating':'bad','genre':[],'library_uuid':{}}, {'rating':0}])
def test_malformed_or_zero_cookie(client, catalogue, value):
    client.set_cookie('libraryFilters', quote(json.dumps(value)))
    response = client.get('/library')
    assert response.status_code == 200
    assert b'Unrated game' in response.data


def test_explicit_clear_and_chip_removal_persist(client, catalogue):
    library, _ = catalogue
    client.set_cookie('libraryFilters', quote(json.dumps({'library_uuid':library.uuid, 'genre':'Missing'})))
    response = client.get('/library')
    doc = Document(response.get_data(as_text=True))
    links = [attrs['href'] for tag,attrs in doc.elements if tag == 'a' and 'filters=1' in attrs.get('href','')]
    remove_genre = next(url for url in links if 'library_uuid=' in url and 'genre=' not in url)
    response = client.get(remove_genre)
    assert b'Unrated game' in response.data
    assert b'Library: Named library' in response.data
    assert b'Unrated game' in client.get('/library').data
    response = client.get('/library?filters=1')
    assert b'library-clear-filters' not in response.data
    assert b'Unrated game' in client.get('/library').data


def test_ajax_card_payloads_are_escaped_and_share_initial_renderer(client, catalogue, db_session):
    library, game = catalogue
    attack = '\" data-audit-injected=\"yes\" onpointerenter=\"void 0\" data-tail=\"'
    game.name = attack
    genre = Genre(name='<img src=x onerror=alert(1)>')
    db_session.add(genre); game.genres.append(genre); db_session.commit()
    response = client.get('/browse_games?render=html&library_uuid='+library.uuid).get_json()
    assert response['total'] == 1
    doc = Document(response['html'])
    assert any(attrs.get('data-name') == attack for _,attrs in doc.elements)
    assert not any('data-audit-injected' in attrs or 'onpointerenter' in attrs or 'onerror' in attrs for _,attrs in doc.elements)
    initial = client.get('/library?library_uuid='+library.uuid).get_data(as_text=True)
    assert response['html'].strip() in initial
    assert 'popupMenu-' not in response['html']
    assert 'Named library' in response['chips_html']
    menu = client.get('/library/game-actions/'+game.uuid)
    assert menu.status_code == 200 and b'popupMenu-' in menu.data


def test_library_markup_benchmark(client, catalogue, db_session):
    library, _ = catalogue
    db_session.add_all([Game(name='Benchmark '+str(i),library_uuid=library.uuid) for i in range(100)])
    db_session.commit()
    samples = {}
    for size in [20,100]:
        url=f'/library?library_uuid={library.uuid}&per_page={size}'
        client.get(url)
        started = perf_counter(); response=client.get(url)
        samples[size] = {'bytes':len(response.data), 'ms':(perf_counter()-started)*1000}
        assert len(response.data) < (186938 if size == 20 else 779243)
    from pathlib import Path
    Path('/tmp/sharewarez-library-benchmark.json').write_text(json.dumps(samples, indent=2))