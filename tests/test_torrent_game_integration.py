from uuid import uuid4
import re
from unittest.mock import patch
import pytest
from sqlalchemy import select
from sharewarez.models import Game, Library, User, UnmatchedFolder
from sharewarez.platform import LibraryPlatform


def test_create_edit_and_browse_without_any_mount(client, db_session, app):
    marker = uuid4().hex[:8]
    library = Library(name='Source library ' + marker, platform=LibraryPlatform.PCWIN)
    admin = User(name='source_admin_' + marker, email=marker + '@example.test', role='admin', password_hash='unused')
    db_session.add_all([library, admin])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    data = dict(name='Source only ' + marker, library_uuid=library.uuid, source_mode='torrent',
                entry_uuid=str(uuid4()),
                manual_identity='1', igdb_id='', status='RELEASED', category='MAIN_GAME',
                source_label='Public release', source_magnet='magnet:?xt=urn:btih:' + uuid4().hex + marker,
                sources_public='1')
    from werkzeug.datastructures import MultiDict
    invalid = MultiDict(data)
    invalid.add('source_label', 'Invalid second source')
    invalid.add('source_magnet', 'https://invalid.example/torrent')
    invalid_result = client.post('/add_game_manual', data=invalid)
    assert invalid_result.status_code == 200
    assert b'Source 2' in invalid_result.data
    assert db_session.query(Game).filter_by(name=data['name']).count() == 0
    from io import BytesIO
    oversized = client.post('/add_game_manual', data={**data, 'source_magnet': '',
                            'source_file': (BytesIO(b'x' * (10 * 1024 * 1024 + 1)), 'too-large.torrent')})
    assert oversized.status_code == 413
    assert data['name'].encode() in oversized.data
    assert b'torrent-source-error' in oversized.data
    assert db_session.query(Game).filter_by(name=data['name']).count() == 0
    with patch('sharewarez.routes_games_ext.add.get_allowed_base_directories', return_value=[]), \
         patch('sharewarez.routes_games_ext.add.is_scan_job_running', side_effect=AssertionError('Source-only creation must bypass scan blocking')), \
         patch('sharewarez.routes_games_ext.add.enqueue_image_refresh'), \
         patch('sharewarez.routes_games_ext.add.read_first_nfo_content') as nfo:
        result = client.post('/add_game_manual', data=data)
        assert result.status_code == 302, re.findall(r'<(?:p|div)[^>]*(?:role="alert"|class="toast-body")[^>]*>(.*?)</(?:p|div)>', result.get_data(as_text=True), re.S)
        nfo.assert_not_called()
        assert client.post('/add_game_manual', data=data).location == result.location
    game = db_session.execute(select(Game).where(Game.name == data['name'])).scalar_one()
    assert game.full_disk_path is None
    assert len(game.torrent_sources) == 1
    assert db_session.query(Game).filter_by(uuid=data['entry_uuid']).count() == 1
    from sharewarez.models import Collection, CollectionGame
    admin.favorites.append(game)
    collection = Collection(name='Source collection ' + marker, slug='source-collection-' + marker)
    db_session.add(collection)
    db_session.flush()
    db_session.add(CollectionGame(collection_id=collection.id, game_uuid=game.uuid))
    db_session.commit()
    assert data['name'].encode() in client.get('/favorites').data
    assert any(item['uuid'] == game.uuid for item in client.get('/api/search', query_string={'query': data['name']}).json)
    assert data['name'].encode() in client.get('/library', query_string={'collection': collection.slug, 'filters': '1'}).data
    detail = client.get('/game_details/' + game.uuid)
    assert detail.status_code == 200, detail.get_data(as_text=True)[-2000:]
    assert b'Open magnet' in detail.data and b'No local files' in detail.data
    assert b'id="gameDownloadForm"' not in detail.data
    listing = client.get('/library?filters=1&source=torrent_only&library_uuid=' + library.uuid)
    assert listing.status_code == 200
    assert data['name'].encode() in listing.data
    with patch('sharewarez.routes_games_ext.edit.get_allowed_base_directories', return_value=[]), \
         patch('sharewarez.routes_games_ext.edit.read_first_nfo_content') as nfo:
        edited = client.post('/game_edit/' + game.uuid, data={**data, 'name': 'Edited ' + marker,
                                                            'source_label': '', 'source_magnet': ''})
        assert edited.status_code == 302, edited.get_data(as_text=True)[-3000:]
        nfo.assert_not_called()
    db_session.expire_all()
    assert game.name == 'Edited ' + marker
    assert len(game.torrent_sources) == 1


def test_attach_candidate_preserves_library_and_sources(client, db_session, tmp_path):
    from sharewarez.utils.torrent_service import attach_prepared, prepare_source
    marker = uuid4().hex[:8]
    original = Library(name='Original ' + marker, platform=LibraryPlatform.PCWIN)
    scanned = Library(name='Scanned ' + marker, platform=LibraryPlatform.PCWIN)
    game = Game(name='Candidate ' + marker, library=original, summary='Preserve manual metadata')
    admin = User(name='attach_admin_' + marker, email=marker + '@attach.test', role='admin', password_hash='unused')
    db_session.add_all([game, scanned, admin])
    admin.favorites.append(game)
    db_session.flush()
    attach_prepared(game, [prepare_source('Release', 'magnet:?xt=urn:btih:' + 'b' * 40, public=True)], admin.id)
    folder_path = tmp_path / 'game'
    folder_path.mkdir()
    (folder_path / 'game.bin').write_bytes(b'game content')
    folder = UnmatchedFolder(folder_path=str(folder_path), candidate_game_uuid=game.uuid,
                             library_uuid=scanned.uuid, status='Duplicate', content_type='Games')
    db_session.add(folder)
    db_session.commit()
    original_uuid, game_uuid = original.uuid, game.uuid
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    with patch('sharewarez.utils.security.get_allowed_base_directories', return_value=[str(tmp_path)]):
        result = client.post('/games/attach-local/' + folder.id)
    assert result.status_code == 302
    db_session.expire_all()
    assert game.uuid == game_uuid and game.library_uuid == original_uuid
    assert game.full_disk_path == str(folder_path)
    assert len(game.torrent_sources) == 1
    assert game.summary == 'Preserve manual metadata'
    assert game in admin.favorites


def test_remove_missing_scan_preserves_pathless_and_torrent_games(app, db_session, tmp_path):
    from sharewarez.models import GlobalSettings, AllowedFileType
    from sharewarez.utilities import scan_and_add_games
    from sharewarez.utils.torrent_service import attach_prepared, prepare_source
    root = tmp_path / 'mounted-games'
    root.mkdir()
    (root / 'Present candidate').mkdir()
    app.config.update(BASE_FOLDER_POSIX=str(root), BASE_FOLDER_WINDOWS=str(root), DATA_FOLDER_WAREZ=str(root))
    library = Library(name='Source scan ' + uuid4().hex[:8], platform=LibraryPlatform.PCWIN)
    pathless = Game(name='Pathless scan fixture', library=library)
    hybrid = Game(name='Missing disk with torrent', library=library, full_disk_path=str(root / 'Missing torrent game'))
    local = Game(name='Missing local only', library=library, full_disk_path=str(root / 'Missing local game'))
    db_session.add_all([pathless, hybrid, local])
    if not db_session.query(GlobalSettings).first():
        db_session.add(GlobalSettings(scan_thread_count=1, update_folder_name='updates', extras_folder_name='extras'))
    if not db_session.query(AllowedFileType).filter_by(value='exe').first():
        db_session.add(AllowedFileType(value='exe'))
    attach_prepared(hybrid, [prepare_source('Release', 'magnet:?xt=urn:btih:' + 'f' * 40, public=True)], None)
    db_session.commit()
    with patch('sharewarez.utilities.is_scan_job_running', return_value=False), \
         patch('sharewarez.utilities.load_scanning_filter_patterns', return_value=([], [])), \
         patch('sharewarez.utilities.process_game_with_fallback', return_value=True), \
         patch('sharewarez.utilities.remove_from_lib', return_value=True) as remove:
        result = scan_and_add_games(str(root), library_uuid=library.uuid, remove_missing=True)
    assert result['outcome'] == 'completed'
    assert [call.args[0] for call in remove.call_args_list] == [local.uuid]
    db_session.expire_all()
    assert pathless.full_disk_path is None
    assert hybrid.full_disk_path == str(root / 'Missing torrent game') and len(hybrid.torrent_sources) == 1


def test_source_filter_counts_and_ajax_share_predicates(client, db_session):
    from sharewarez.utils.torrent_service import attach_prepared, prepare_source
    marker = uuid4().hex[:8]
    library = Library(name='Filter fixtures ' + marker, platform=LibraryPlatform.PCWIN)
    local = Game(name='Local ' + marker, library=library, full_disk_path='/registered/local')
    hybrid = Game(name='Hybrid ' + marker, library=library, full_disk_path='/registered/hybrid')
    remote = Game(name='Remote ' + marker, library=library)
    user = User(name='filter_member_' + marker, email=marker + '@filter.test', role='user', password_hash='unused')
    db_session.add_all([local, hybrid, remote, user])
    for game in (hybrid, remote):
        attach_prepared(game, [prepare_source('Public source', 'magnet:?xt=urn:btih:' + uuid4().hex + marker, public=True)], None)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    for source, expected in [('local', {local.name, hybrid.name}), ('torrent', {hybrid.name, remote.name}),
                             ('torrent_only', {remote.name})]:
        query = f'?filters=1&source={source}&library_uuid={library.uuid}'
        response = client.get('/browse_games' + query + '&render=html')
        assert response.status_code == 200
        assert response.json['total'] == len(expected)
        assert {game['name'] for game in response.json['games']} == expected
        assert 'magnet:?' not in response.get_data(as_text=True)
        initial = client.get('/library' + query)
        assert initial.status_code == 200
        for name in expected:
            assert name.encode() in initial.data
        assert b'Add game</a>' not in initial.data


def test_card_opens_single_magnet_and_lists_multiple_sources(client, db_session):
    from sharewarez.routes_library import serialize_library_cards
    from sharewarez.utils.torrent_service import attach_prepared, prepare_source
    marker = uuid4().hex[:8]
    library = Library(name='Card sources ' + marker, platform=LibraryPlatform.PCWIN)
    game = Game(name='Card magnet ' + marker, library=library)
    user = User(name='card_member_' + marker, email=marker + '@cards.test', role='user', password_hash='unused')
    db_session.add_all([game, user])
    attach_prepared(game, [prepare_source('Primary', 'magnet:?xt=urn:btih:' + uuid4().hex + marker, public=True)], None)
    db_session.commit()
    source_id = game.torrent_sources[0].id
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    cards = serialize_library_cards([game], user.id)
    assert cards[0]['single_magnet_source_id'] == source_id
    query = '?library_uuid=' + library.uuid
    initial = client.get('/library' + query)
    assert b'data-card-magnet-url=' in initial.data
    assert b'magnet:?' not in initial.data
    ajax = client.get('/browse_games' + query + '&render=html')
    assert 'data-card-magnet-url=' in ajax.json['html']
    # Use the same authenticated URL generated on the card.
    import re
    source_url = re.search(r'data-card-magnet-url="([^"]+)"', initial.get_data(as_text=True)).group(1)
    response = client.get(source_url)
    assert response.status_code == 200
    assert response.json['magnet'].startswith('magnet:?')
    attach_prepared(game, [prepare_source('Alternative', 'magnet:?xt=urn:btih:' + uuid4().hex + marker, public=True)], None)
    db_session.commit()
    assert serialize_library_cards([game], user.id)[0]['single_magnet_source_id'] is None
    multiple = client.get('/library' + query)
    assert b'data-card-magnet-url=' not in multiple.data
    assert b'#torrent-sources-title' in multiple.data


def test_local_game_keeps_local_download_and_separate_torrent_actions(client, db_session, tmp_path):
    from sharewarez.models import DownloadRequest
    from sharewarez.utils.torrent_service import attach_prepared, prepare_source
    marker = uuid4().hex[:8]
    path = tmp_path / 'game.bin'
    path.write_bytes(b'local game fixture')
    library = Library(name='Hybrid downloads ' + marker, platform=LibraryPlatform.PCWIN)
    game = Game(name='Hybrid download ' + marker, library=library, full_disk_path=str(path), size=path.stat().st_size)
    member = User(name='hybrid_member_' + marker, email=marker + '@hybrid.test', role='user', password_hash='unused')
    db_session.add_all([game, member])
    attach_prepared(game, [prepare_source('Alternative release', 'magnet:?xt=urn:btih:' + uuid4().hex + marker, public=True)], None)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(member.id)
        session['_fresh'] = True
    source = game.torrent_sources[0]
    assert client.get(f'/games/{game.uuid}/torrent-sources/{source.id}/magnet').status_code == 200
    assert db_session.query(DownloadRequest).filter_by(game_uuid=game.uuid).count() == 0
    db_session.refresh(game)
    assert game.times_downloaded == 0
    with patch('sharewarez.utils.download_creation.get_allowed_base_directories', return_value=[str(tmp_path)]):
        confirmation = client.get('/download_game/' + game.uuid)
        assert confirmation.status_code == 200
        assert db_session.query(DownloadRequest).filter_by(game_uuid=game.uuid).count() == 0
        response = client.post('/download_game/' + game.uuid)
        assert response.status_code == 302
    request = db_session.query(DownloadRequest).filter_by(game_uuid=game.uuid).one()
    assert request.delivery_kind == 'direct'
    assert request.file_location == str(path)
    assert game.full_disk_path == str(path)


def test_identified_game_can_be_created_without_local_files(client, db_session):
    marker = uuid4().hex[:8]
    library = Library(name='Identified source ' + marker, platform=LibraryPlatform.PCWIN)
    admin = User(name='identified_admin_' + marker, email=marker + '@identified.test', role='admin', password_hash='unused')
    db_session.add_all([library, admin])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    provider_id = uuid4().int % 900000000 + 1000
    data = dict(name='Identified source game ' + marker, library_uuid=library.uuid, source_mode='torrent',
                manual_identity='0', igdb_id=str(provider_id), status='RELEASED', category='MAIN_GAME',
                source_label='Public release', source_magnet='magnet:?xt=urn:btih:' + uuid4().hex + marker,
                sources_public='1')
    with patch('sharewarez.routes_games_ext.add.enqueue_image_refresh'), \
         patch('sharewarez.routes_games_ext.add.refresh_game_metadata_and_updates'), \
         patch('sharewarez.routes_games_ext.add.get_allowed_base_directories', return_value=[]):
        response = client.post('/add_game_manual', data=data)
    assert response.status_code == 302, response.get_data(as_text=True)[response.get_data(as_text=True).find('game-edit-error-summary'):][:1500]
    game = db_session.query(Game).filter_by(igdb_id=provider_id).one()
    assert game.full_disk_path is None and len(game.torrent_sources) == 1
    assert game.library_uuid == library.uuid
    assert any(identity.provider == 'igdb' and identity.external_id == str(provider_id)
               for identity in game.external_identities)


def test_add_refresh_completes_provider_metadata_and_preserves_manual_edits(client, db_session):
    from datetime import date
    from sharewarez.models import Category, Status
    marker = uuid4().hex[:8]
    library = Library(name='Enriched source ' + marker, platform=LibraryPlatform.PCWIN)
    admin = User(name='enrich_admin_' + marker, email=marker + '@enrich.test', role='admin', password_hash='unused')
    db_session.add_all([library, admin])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    provider_id = uuid4().int % 900000000 + 1000
    payload = dict(id=provider_id, name='Provider title', summary='Provider summary',
                   first_release_date=946684800, category=2, status=0, aggregated_rating=82.5,
                   genres=[{'id': 8, 'name': 'Enriched genre ' + marker}],
                   collections=[{'id': provider_id, 'name': 'Provider collection ' + marker}],
                   videos=[{'video_id': 'abc123'}])
    data = dict(name='Manual title ' + marker, summary='Manual summary', aggregated_rating='64',
                library_uuid=library.uuid, source_mode='torrent', manual_identity='0', igdb_id=str(provider_id),
                action='save_and_refresh', source_label='Public release',
                source_magnet='magnet:?xt=urn:btih:' + uuid4().hex + marker, sources_public='1')
    with patch('sharewarez.utilities.fetch_game_by_igdb_id', return_value=[payload]), \
         patch('sharewarez.routes_games_ext.add.enqueue_image_refresh') as artwork:
        response = client.post('/add_game_manual', data=data)
    assert response.status_code == 302
    game = db_session.query(Game).filter_by(igdb_id=provider_id).one()
    assert game.name == data['name'] and game.summary == 'Manual summary'
    assert game.aggregated_rating == 64
    assert game.first_release_date.date() == date(2000, 1, 1)
    assert game.category == Category.EXPANSION and game.status == Status.RELEASED
    assert game.video_urls == 'https://www.youtube.com/embed/abc123'
    assert [genre.name for genre in game.genres] == ['Enriched genre ' + marker]
    assert game.metadata_provenance['summary']['source'] == 'manual'
    assert game.metadata_provider_values['summary']['value'] == 'Provider summary'
    artwork.assert_called_once_with(game.uuid, expected_igdb_id=provider_id, audit_user_id=admin.id, commit=False)


def test_source_selection_preserves_local_path_until_explicit_detach(client, db_session):
    marker = uuid4().hex[:8]
    library = Library(name='Detach source ' + marker, platform=LibraryPlatform.PCWIN)
    game = Game(name='Local game ' + marker, library=library, full_disk_path='/registered/local/' + marker)
    admin = User(name='detach_admin_' + marker, email=marker + '@detach.test', role='admin', password_hash='unused')
    db_session.add_all([game, admin])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    data = dict(name=game.name, library_uuid=library.uuid, source_mode='torrent', manual_identity='1',
                status='RELEASED', category='MAIN_GAME', source_label='Alternative',
                source_magnet='magnet:?xt=urn:btih:' + uuid4().hex + marker, sources_public='1')
    with patch('sharewarez.routes_games_ext.edit.get_allowed_base_directories', return_value=['/registered']), \
         patch('sharewarez.routes_games_ext.edit.is_safe_path', return_value=(True, '')), \
         patch('sharewarez.routes_games_ext.edit.get_folder_size_in_bytes_updates', return_value=1024), \
         patch('sharewarez.routes_games_ext.edit.read_first_nfo_content', return_value=None):
        assert client.post('/game_edit/' + game.uuid, data=data).status_code == 302
    db_session.refresh(game)
    assert game.full_disk_path == '/registered/local/' + marker
    assert game.size == 1024 and len(game.torrent_sources) == 1
    detached = client.post('/game_edit/' + game.uuid, data={**data, 'detach_local': 'y', 'source_label': '', 'source_magnet': ''})
    assert detached.status_code == 302
    db_session.refresh(game)
    assert game.full_disk_path is None and game.size == 0 and len(game.torrent_sources) == 1


@pytest.mark.parametrize('explicitly_cleared', [False, True])
def test_add_enriches_untouched_form_defaults_but_keeps_explicit_clears(client, db_session, explicitly_cleared):
    from sharewarez.models import Category, Status
    marker = uuid4().hex[:8]
    library = Library(name='Tracked metadata ' + marker, platform=LibraryPlatform.PCWIN)
    admin = User(name='tracked_admin_' + marker, email=marker + '@tracked.test', role='admin', password_hash='unused')
    db_session.add_all([library, admin])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    provider_id = uuid4().int % 900000000 + 1000
    payload = dict(id=provider_id, name='Provider title', summary='Fetched summary',
                   category=2, status=4, aggregated_rating=95,
                   genres=[{'id': 8, 'name': 'Tracked genre ' + marker}])
    data = dict(name='Manual draft ' + marker, summary='', aggregated_rating='',
                first_release_date='', category='MAIN_GAME', status='RELEASED', video_urls='',
                library_uuid=library.uuid, source_mode='torrent', manual_identity='0', igdb_id=str(provider_id),
                metadata_tracking_active='1',
                metadata_manual_fields='["name", "summary", "genres"]' if explicitly_cleared else '["name"]',
                source_label='Public release', source_magnet='magnet:?xt=urn:btih:' + uuid4().hex + marker,
                sources_public='1')
    with patch('sharewarez.utilities.fetch_game_by_igdb_id', return_value=[payload]), \
         patch('sharewarez.routes_games_ext.add.enqueue_image_refresh'):
        response = client.post('/add_game_manual', data=data)
    assert response.status_code == 302
    game = db_session.query(Game).filter_by(igdb_id=provider_id).one()
    assert game.name == data['name']
    assert game.category == Category.EXPANSION and game.status == Status.EARLY_ACCESS
    assert game.aggregated_rating == 95
    assert game.summary == ('' if explicitly_cleared else 'Fetched summary')
    assert [genre.name for genre in game.genres] == ([] if explicitly_cleared else ['Tracked genre ' + marker])
    if explicitly_cleared:
        assert game.metadata_provenance['summary']['source'] == 'manual'
    else:
        assert game.metadata_provenance['summary']['source'] == 'igdb'
