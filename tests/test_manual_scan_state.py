import json
from urllib.parse import urlencode
from uuid import uuid4

from bs4 import BeautifulSoup
import pytest

from sharewarez.models import AllowedFileType, Game, GlobalSettings, Library, User
from sharewarez.platform import LibraryPlatform


@pytest.fixture
def manual_storage(app, db_session, client, tmp_path):
    app.config.update(BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path), DATA_FOLDER_WAREZ=str(tmp_path))
    suffix = uuid4().hex
    user = User(name=suffix, email=f'{suffix}@example.test', role='admin', password_hash='unused')
    library = Library(name=suffix, platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library])
    for extension in ('iso', 'zip'):
        if not db_session.query(AllowedFileType).filter_by(value=extension).first():
            db_session.add(AllowedFileType(value=extension))
    db_session.commit()
    with client.session_transaction() as state:
        state['_user_id'] = str(user.id)
        state['_fresh'] = True
    return client, library, tmp_path


def listing(client, library, **fields):
    return client.post('/admin/scan_management', data={'submit': 'ManualScan', 'folder_path': '.', 'scan_mode': 'files', 'library_uuid': library.uuid, **fields}, follow_redirects=True)


def selections(response):
    soup = BeautifulSoup(response.data, 'html.parser')
    return [{item['name']: item.get('value', '') for item in form.select('input[type=hidden][name]')}
            for form in soup.select('.admin_manage_scanjobs-foudngames-list form')]


def identify_url(selection):
    return '/add_game_manual?' + urlencode(selection)


def test_equal_cleaned_titles_remain_distinct_after_reload(manual_storage):
    client, library, root = manual_storage
    for name in ('Game.iso', 'Game.zip'):
        (root / name).write_bytes(b'fixture')
    response = listing(client, library)
    choices = selections(response)
    assert len(choices) == 2
    assert {choice['candidate_path'] for choice in choices} == {'Game.iso', 'Game.zip'}
    assert all('full_disk_path' not in choice for choice in choices)
    assert selections(client.get('/admin/scan_management?active_tab=manual')) == choices
    paths = []
    for choice in choices:
        page = client.get(identify_url(choice))
        assert page.status_code == 200
        field = BeautifulSoup(page.data, 'html.parser').select_one('[name=full_disk_path]')
        paths.append(field['value'])
        assert field.has_attr('readonly')
    assert set(paths) == {str(root / 'Game.iso'), str(root / 'Game.zip')}


def test_large_list_is_paginated_without_candidate_paths_in_cookie(manual_storage):
    client, library, root = manual_storage
    for index in range(650):
        (root / f'Game {index:04}.iso').touch()
    first = selections(listing(client, library))
    second = selections(client.get('/admin/scan_management?active_tab=manual&manual_page=2'))
    assert len(first) == len(second) == 50
    assert not {item['candidate_path'] for item in first} & {item['candidate_path'] for item in second}
    assert first[0]['selection_generation'] == second[0]['selection_generation']
    with client.session_transaction() as state:
        assert 'game_paths' not in state
        assert len(json.dumps(dict(state))) < 1800
        assert 'Game 0000.iso' not in json.dumps(dict(state))


@pytest.mark.parametrize('change', ['new_generation', 'removed', 'mode', 'root', 'library', 'path_escape'])
def test_stale_or_unsafe_candidate_is_rejected_on_get_and_post(manual_storage, app, db_session, change):
    client, library, root = manual_storage
    game = root / 'Game.iso'
    game.write_bytes(b'fixture')
    choice = selections(listing(client, library))[0]
    if change == 'new_generation':
        listing(client, library)
    elif change == 'removed':
        game.unlink()
    elif change == 'mode':
        game.unlink()
        game.mkdir()
    elif change == 'root':
        new_root = root / 'other'
        new_root.mkdir()
        app.config['BASE_FOLDER_POSIX'] = str(new_root)
    elif change == 'library':
        db_session.delete(library)
        db_session.commit()
    else:
        choice['candidate_path'] = '../outside.iso'
    url = identify_url(choice)
    assert client.get(url).status_code == 302
    before = db_session.query(Game).count()
    response = client.post(url, data={**choice, 'full_disk_path': str(game), 'manual_identity': '1', 'name': 'Game'})
    assert response.status_code == 302 and '/admin/scan_management' in response.location
    assert db_session.query(Game).count() == before


@pytest.mark.parametrize('tamper', ['library_uuid', 'full_disk_path', 'selection_generation', 'candidate_path'])
def test_identify_post_cannot_replace_selection_identity(manual_storage, db_session, tamper):
    client, library, root = manual_storage
    (root / 'Game.iso').touch()
    (root / 'Other.iso').touch()
    choice = selections(listing(client, library))[0]
    data = {**choice, 'full_disk_path': str(root / choice['candidate_path']), 'manual_identity': '1', 'name': 'Game'}
    data[tamper] = str(uuid4()) if tamper == 'library_uuid' else ('Other.iso' if tamper == 'candidate_path' else 'changed')
    before = db_session.query(Game).count()
    assert client.post(identify_url(choice), data=data).status_code == 302
    assert db_session.query(Game).count() == before


def test_failed_new_list_clears_previous_and_legacy_results(manual_storage):
    client, library, root = manual_storage
    (root / 'Game.iso').touch()
    listing(client, library)
    with client.session_transaction() as state:
        state['game_paths'] = {'old': '/old/path'}
    response = listing(client, library, folder_path='missing')
    assert selections(response) == []
    with client.session_transaction() as state:
        assert 'game_paths' not in state and 'manual_scan_selection' not in state


def test_list_is_read_only_even_when_metadata_writing_is_enabled(manual_storage, db_session):
    from unittest.mock import patch
    client, library, root = manual_storage
    (root / 'Game.iso').touch()
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.write_local_metadata = True
    db_session.commit()
    with patch('sharewarez.utils.local_metadata.check_library_write_permissions', side_effect=AssertionError('listing must not probe writes')):
        assert len(selections(listing(client, library))) == 1


def test_switching_library_invalidates_old_tab(manual_storage, db_session):
    client, library, root = manual_storage
    (root / 'Game.iso').touch()
    choice = selections(listing(client, library))[0]
    other = Library(name=f'Other {uuid4().hex}', platform=LibraryPlatform.PCWIN)
    db_session.add(other)
    db_session.commit()
    client.get(f'/admin/scan_management?active_tab=manual&library_uuid={other.uuid}')
    assert client.get(identify_url(choice)).status_code == 302


def test_equal_titles_can_both_be_saved_independently(manual_storage, db_session):
    from unittest.mock import patch
    client, library, root = manual_storage
    for name in ('Game.iso', 'Game.zip'):
        (root / name).touch()
    choices = selections(listing(client, library))
    with patch('sharewarez.routes_games_ext.add.Thread.start'), patch('sharewarez.routes_games_ext.add.read_first_nfo_content', return_value=None):
        for choice in choices:
            response = client.post(identify_url(choice), data={**choice, 'full_disk_path': str(root / choice['candidate_path']),
                'manual_identity': '1', 'igdb_id': '', 'name': 'Game', 'status': 'RELEASED', 'category': 'MAIN_GAME'})
            assert response.status_code == 302
    games = db_session.query(Game).filter_by(library_uuid=library.uuid).all()
    assert len(games) == 2
    assert {game.full_disk_path for game in games} == {str(root / 'Game.iso'), str(root / 'Game.zip')}


@pytest.mark.parametrize('include_times', [False, True])
@pytest.mark.parametrize('enabled_at_identify', [False, True])
def test_manual_identify_rechecks_hltb_policy_after_listing(manual_storage, db_session, enabled_at_identify, include_times):
    from unittest.mock import patch
    client, library, root = manual_storage
    (root / 'Game.iso').touch()
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings(); db_session.add(settings)
    settings.enable_hltb_integration = True; settings.write_local_metadata = False
    db_session.commit()
    choice = selections(listing(client, library, fetch_hltb='on' if include_times else '', force_hltb_refetch='on'))[0]
    settings.enable_hltb_integration = enabled_at_identify
    db_session.commit()
    with patch('sharewarez.routes_games_ext.add.Thread.start'), patch('sharewarez.routes_games_ext.add.read_first_nfo_content',return_value=None), patch('sharewarez.utils.hltb.update_game_hltb_sync') as lookup:
        response = client.post(identify_url(choice), data={**choice,'full_disk_path':str(root/'Game.iso'),'manual_identity':'1','igdb_id':'','name':'Game','status':'RELEASED','category':'MAIN_GAME'})
    assert response.status_code == 302
    assert lookup.call_count == int(enabled_at_identify and include_times)
    assert db_session.query(Game).filter_by(library_uuid=library.uuid).count() == 1


def test_all_scan_hltb_controls_disabled_by_global_policy(manual_storage, db_session):
    client, library, root = manual_storage
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings(); db_session.add(settings)
    settings.enable_hltb_integration = False
    db_session.commit()
    page = BeautifulSoup(client.get('/admin/scan_management').data,'html.parser')
    controls = page.select('[name=fetch_hltb], [name=force_hltb_refetch]')
    assert len(controls) == 6 and all(control.has_attr('disabled') for control in controls)
    advanced = page.select('details.scan-advanced-options')
    assert len(advanced) == 3 and all(len(item.select('[name=fetch_hltb], [name=force_hltb_refetch]')) == 2 for item in advanced)
    assert all(item.select_one('a[href="/admin/settings?section=metadata"]') is not None for item in advanced)
    assert all(not control.find_parent('details', class_='scan-advanced-options') for control in page.select('[name=remove_missing]'))

    settings.enable_hltb_integration = True
    db_session.commit()
    page = BeautifulSoup(client.get('/admin/scan_management').data,'html.parser')
    assert all(not control.has_attr('disabled') for control in page.select('[name=fetch_hltb], [name=force_hltb_refetch]'))
