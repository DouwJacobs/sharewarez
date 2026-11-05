"""Scan Manager form payloads must reach the real listing handler."""
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from sharewarez.models import Library, User
from sharewarez.platform import LibraryPlatform


@pytest.fixture
def scan_picker(app, client, db_session, tmp_path):
    suffix = uuid4().hex
    admin = User(name=suffix, email=f'{suffix}@example.com', role='admin', password_hash='unused')
    library = Library(name=f'Picker {suffix}', platform=LibraryPlatform.PCWIN)
    db_session.add_all([admin, library])
    db_session.commit()
    app.config.update(BASE_FOLDER_POSIX=str(tmp_path), BASE_FOLDER_WINDOWS=str(tmp_path))
    # Discovery uses the configured allowed game-storage root too.
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    return client, library, tmp_path


def test_rendered_manual_form_posts_without_submitter(scan_picker):
    client, library, root = scan_picker
    (root / 'Picker Game').mkdir()
    page = client.get('/admin/scan_management?active_tab=manual')
    soup = BeautifulSoup(page.data, 'html.parser')
    form = soup.select_one('#manualScan form')
    payload = {item['name']: item.get('value', '') for item in form.select('input[type=hidden][name]')}
    assert payload['submit'] == 'ManualScan'
    assert not form.select_one('#manualScanSubmitBtn').has_attr('name')
    payload.update(folder_path='.', library_uuid=str(library.uuid), scan_mode='folders')
    response = client.post('/admin/scan_management', data=payload, follow_redirects=True)
    assert response.status_code == 200
    assert b'Picker Game' in response.data
    assert b'Unrecognized action' not in response.data
    with client.session_transaction() as session:
        assert session['game_paths']['Picker Game'] == str(root / 'Picker Game')


@pytest.mark.parametrize('kind,action', [('manual', 'ManualScan'), ('auto', 'AutoScan')])
def test_failed_submit_preserves_draft_in_scan_workspace(scan_picker, kind, action):
    client, library, _ = scan_picker
    response = client.post('/admin/scan_management', data={
        'submit': action, 'folder_path': 'missing', 'scan_mode': 'files',
        'library_uuid': str(library.uuid), 'force_hltb_refetch': 'y',
    }, follow_redirects=True)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    form = soup.select_one(f'#{kind}Scan form')
    assert form.select_one('[name=folder_path]')['value'] == 'missing'
    assert form.select_one('[name=library_uuid] option[selected]')['value'] == str(library.uuid)
    assert form.select_one('[name=scan_mode][checked]')['value'] == 'files'
    assert form.select_one('[name=force_hltb_refetch]').has_attr('checked')
    assert not form.select_one('[name=fetch_hltb]').has_attr('checked')
