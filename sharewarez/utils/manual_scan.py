"""Bounded manual selection state; candidates are re-enumerated on demand."""
import hashlib
import math
import os
from uuid import uuid4

from flask import current_app, session
from flask_login import current_user
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import AllowedFileType, Library
from sharewarez.utils.functions import load_scanning_filter_patterns
from sharewarez.utils.scan_targets import enumerate_scan_target, resolve_scan_target, validate_scan_candidate, within


STATE_KEY = 'manual_scan_selection'
PAGE_SIZE = 50


class StaleManualSelection(ValueError):
    pass


def clear_manual_selection():
    for key in (STATE_KEY, 'game_paths', 'force_updates_extras_scan', 'fetch_hltb', 'force_hltb_refetch',
                'permission_check_failed', 'permission_errors', 'permission_check_path'):
        session.pop(key, None)


def _root_token(root):
    info = os.stat(root)
    return hashlib.sha256(f'{root}\0{info.st_dev}\0{info.st_ino}'.encode()).hexdigest()


def start_manual_selection(library_uuid, target, options):
    active = 'BASE_FOLDER_WINDOWS' if os.name == 'nt' else 'BASE_FOLDER_POSIX'
    for key in (active, 'DATA_FOLDER_WAREZ', 'BASE_FOLDER_WINDOWS', 'BASE_FOLDER_POSIX'):
        configured = current_app.config.get(key)
        if not configured or not os.path.isabs(configured):
            continue
        root = os.path.realpath(configured)
        if within(target.path, root):
            session[STATE_KEY] = {
                'owner': str(current_user.id), 'generation': uuid4().hex,
                'library_uuid': str(library_uuid), 'root_key': key,
                'root_token': _root_token(root),
                'target': os.path.relpath(target.path, root), 'mode': target.mode,
                'identity': [target.device, target.inode], 'options': dict(options),
            }
            session['selected_library_uuid'] = str(library_uuid)
            return
    raise StaleManualSelection('The selected storage root is no longer configured. List games again.')


def _selection():
    state = session.get(STATE_KEY)
    if not isinstance(state, dict) or state.get('owner') != str(current_user.id):
        raise StaleManualSelection('This manual selection is stale. List games again.')
    if db.session.get(Library, state.get('library_uuid')) is None:
        raise StaleManualSelection('The selected library no longer exists. List games again.')
    configured = current_app.config.get(state.get('root_key'))
    if not configured:
        raise StaleManualSelection('The selected storage root is unavailable. List games again.')
    root = os.path.realpath(configured)
    if _root_token(root) != state.get('root_token'):
        raise StaleManualSelection('The configured storage root changed. List games again.')
    path = os.path.normpath(os.path.join(root, state['target']))
    extensions = db.session.execute(select(AllowedFileType.value)).scalars().all()
    target = resolve_scan_target(path, state['mode'], extensions=extensions)
    if not within(target.path, root) or [target.device, target.inode] != state.get('identity'):
        raise StaleManualSelection('The selected scan target changed. List games again.')
    return state, root, target, extensions


def _candidates():
    state, root, target, extensions = _selection()
    candidates, complete = enumerate_scan_target(target, extensions, *load_scanning_filter_patterns())
    for candidate in candidates:
        candidate['relative_path'] = os.path.relpath(candidate['full_path'], root).replace(os.sep, '/')
        candidate['generation'] = state['generation']
        candidate['library_uuid'] = state['library_uuid']
    candidates.sort(key=lambda item: item['relative_path'])
    return state, target, candidates, complete


def manual_candidate_page(page=1):
    state, _, candidates, complete = _candidates()
    pages = max(1, math.ceil(len(candidates) / PAGE_SIZE))
    page = min(max(page, 1), pages)
    return {
        'items': candidates[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
        'total': len(candidates), 'page': page, 'pages': pages,
        'generation': state['generation'], 'library_uuid': state['library_uuid'],
        'complete': complete,
    }


def resolve_manual_candidate(generation, relative_path, library_uuid=None):
    stored = session.get(STATE_KEY) or {}
    if generation != stored.get('generation'):
        raise StaleManualSelection('This manual selection is stale. List games again.')
    state, target, candidates, _ = _candidates()
    if generation != state['generation'] or (library_uuid is not None and str(library_uuid) != state['library_uuid']):
        raise StaleManualSelection('This selection belongs to an older list or another library. List games again.')
    for candidate in candidates:
        if candidate['relative_path'] == relative_path:
            validate_scan_candidate(target, candidate['full_path'])
            return candidate
    raise StaleManualSelection('This candidate was removed, moved or is no longer eligible. List games again.')
