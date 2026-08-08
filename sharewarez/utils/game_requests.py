from datetime import datetime, timezone
from copy import deepcopy
import re
from threading import Lock
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from sharewarez import db
from sharewarez.models import Game, GameRequest, GameRequestUser, GlobalSettings
from sharewarez.utils.igdb_api import make_igdb_api_request


REQUEST_STATUSES = ('pending', 'reviewing', 'planned', 'fulfilled', 'not_planned', 'cancelled')
RESOLVED_STATUSES = {'fulfilled', 'not_planned', 'cancelled'}
DEFAULT_REQUEST_SETTINGS = {
    'enableGameRequests': True,
    'allowRequestNotes': True,
    'allowRequestAnyEdition': True,
    'maxActiveRequestsPerUser': 20,
    'notifyRequesterRequestEmail': True,
    'notifyAdminRequestEmail': False,
    'notifyDiscordNewRequests': False,
    'notifyDiscordRequestUpdates': False,
}
_search_cache = {}
_search_cache_lock = Lock()
_SEARCH_CACHE_TTL_SECONDS = 300
_SEARCH_CACHE_MAX_ENTRIES = 128


def get_request_settings():
    record = db.session.execute(select(GlobalSettings)).scalars().first()
    values = DEFAULT_REQUEST_SETTINGS.copy()
    if record and record.settings:
        values.update({key: record.settings[key] for key in values if key in record.settings})
    return values


def _cover_url(game_data):
    cover = game_data.get('cover') or {}
    image_id = cover.get('image_id') if isinstance(cover, dict) else None
    return f'https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg' if image_id else None


def _parent_id(game_data):
    parent = game_data.get('version_parent')
    if isinstance(parent, dict):
        return int(parent.get('id') or game_data['id'])
    return int(parent or game_data['id'])


def normalize_igdb_game(game_data):
    release_timestamp = game_data.get('first_release_date')
    release_date = None
    if release_timestamp:
        release_date = datetime.fromtimestamp(int(release_timestamp), tz=timezone.utc)
    parent = game_data.get('version_parent')
    parent_name = parent.get('name') if isinstance(parent, dict) else None
    return {
        'igdb_id': int(game_data['id']),
        'parent_igdb_id': _parent_id(game_data),
        'parent_game_name': str(parent_name or game_data.get('name') or '').strip(),
        'game_name': str(game_data.get('name') or '').strip(),
        'edition_name': str(game_data.get('version_title') or '').strip() or None,
        'cover_url': _cover_url(game_data),
        'summary': str(game_data.get('summary') or '').strip() or None,
        'platforms': [item.get('name') for item in game_data.get('platforms', []) if isinstance(item, dict) and item.get('name')],
        'first_release_date': release_date,
    }


IGDB_REQUEST_FIELDS = (
    'fields id,name,version_parent.name,version_title,cover.image_id,summary,'
    'platforms.name,first_release_date;'
)


def fetch_igdb_game(igdb_id):
    response = make_igdb_api_request(
        'https://api.igdb.com/v4/games',
        f'{IGDB_REQUEST_FIELDS} where id = {int(igdb_id)}; limit 1;',
    )
    if not isinstance(response, list) or not response:
        return None
    return normalize_igdb_game(response[0])


def search_igdb_games(term):
    safe_term = re.sub(r"[^\w\s\-:&+().'\u00c0-\u024f]", ' ', term).strip()
    cache_key = safe_term.casefold()
    now = monotonic()
    with _search_cache_lock:
        cached = _search_cache.get(cache_key)
        if cached and cached[0] > now:
            return deepcopy(cached[1]), None
    response = make_igdb_api_request(
        'https://api.igdb.com/v4/games',
        f'{IGDB_REQUEST_FIELDS} search "{safe_term}"; limit 10;',
    )
    if not isinstance(response, list):
        return [], response.get('error') if isinstance(response, dict) else 'IGDB search failed'
    results = [normalize_igdb_game(item) for item in response]
    with _search_cache_lock:
        expired = [key for key, value in _search_cache.items() if value[0] <= now]
        for key in expired:
            _search_cache.pop(key, None)
        if len(_search_cache) >= _SEARCH_CACHE_MAX_ENTRIES:
            _search_cache.pop(next(iter(_search_cache)))
        _search_cache[cache_key] = (now + _SEARCH_CACHE_TTL_SECONDS, deepcopy(results))
    return results, None


def fetch_related_editions(igdb_id):
    selected = fetch_igdb_game(igdb_id)
    if not selected:
        return []
    parent_id = selected['parent_igdb_id']

    # IGDB commonly exposes commercial editions through games.version_parent
    # without a corresponding game_versions record. Query that relationship
    # directly first so Gold/Deluxe/etc. releases are not silently omitted.
    related_games = make_igdb_api_request(
        'https://api.igdb.com/v4/games',
        f'{IGDB_REQUEST_FIELDS} where id = {parent_id} | version_parent = {parent_id}; limit 50;',
    )
    related_by_id = {}
    if isinstance(related_games, list):
        related_by_id.update(
            (item['igdb_id'], item)
            for item in (normalize_igdb_game(game) for game in related_games)
        )
    related_by_id[selected['igdb_id']] = selected

    # Retain the game_versions lookup as a fallback/supplement for IGDB groups
    # that contain related releases without version_parent metadata.
    versions = make_igdb_api_request(
        'https://api.igdb.com/v4/game_versions',
        f'fields games; where game = {parent_id}; limit 50;',
    )
    edition_ids = {parent_id, int(igdb_id)}
    if isinstance(versions, list):
        for version in versions:
            edition_ids.update(int(value) for value in (version.get('games') or []))
    missing_ids = edition_ids.difference(related_by_id)
    if missing_ids:
        ids = ','.join(str(value) for value in sorted(missing_ids))
        response = make_igdb_api_request(
            'https://api.igdb.com/v4/games',
            f'{IGDB_REQUEST_FIELDS} where id = ({ids}); limit 50;',
        )
        if isinstance(response, list):
            related_by_id.update(
                (item['igdb_id'], item)
                for item in (normalize_igdb_game(game) for game in response)
            )
    return sorted(related_by_id.values(), key=lambda item: (item['igdb_id'] != parent_id, item['game_name']))


def enrich_request_search(results, user_id):
    ids = [item['igdb_id'] for item in results]
    if not ids:
        return results
    games = db.session.execute(select(Game).where(Game.igdb_id.in_(ids))).scalars().all()
    requests = db.session.execute(
        select(GameRequest)
        .options(selectinload(GameRequest.requesters))
        .where(GameRequest.igdb_id.in_(ids))
    ).scalars().all()
    games_by_id = {game.igdb_id: game for game in games}
    requests_by_id = {item.igdb_id: item for item in requests}
    for item in results:
        local_game = games_by_id.get(item['igdb_id'])
        game_request = requests_by_id.get(item['igdb_id'])
        item['available_game_uuid'] = local_game.uuid if local_game else None
        item['request_id'] = game_request.id if game_request else None
        item['request_status'] = game_request.status if game_request else None
        item['can_join_request'] = bool(
            game_request and game_request.status in {'pending', 'reviewing', 'planned'}
        )
        item['requester_count'] = len(game_request.interested_requesters) if game_request else 0
        item['requested_by_user'] = bool(game_request and any(link.user_id == user_id and link.withdrawn_at is None for link in game_request.requesters))
    return results


def create_or_join_request(user, igdb_id, note=None, accept_any_edition=False):
    settings = get_request_settings()
    if not settings['enableGameRequests']:
        raise ValueError('Game requests are disabled.')
    if db.session.execute(select(Game).filter_by(igdb_id=int(igdb_id))).scalars().first():
        raise ValueError('This game is already available in the library.')

    game_request = db.session.execute(select(GameRequest).filter_by(igdb_id=int(igdb_id))).scalars().first()
    link = None
    if game_request:
        link = db.session.execute(
            select(GameRequestUser).filter_by(request_id=game_request.id, user_id=user.id)
        ).scalars().first()
        if game_request.status in {'fulfilled', 'not_planned'}:
            raise ValueError('This request has already been resolved.')
    if link and link.withdrawn_at is None:
        raise ValueError('You have already requested this edition.')

    active_count = db.session.execute(
        select(func.count(GameRequestUser.id)).join(GameRequest).where(
            GameRequestUser.user_id == user.id,
            GameRequestUser.withdrawn_at.is_(None),
            GameRequestUser.satisfied_at.is_(None),
            ~GameRequest.status.in_(RESOLVED_STATUSES),
        )
    ).scalar_one()
    if active_count >= int(settings['maxActiveRequestsPerUser']):
        raise ValueError('You have reached the active game request limit.')

    if not game_request:
        snapshot = fetch_igdb_game(igdb_id)
        if not snapshot or not snapshot['game_name']:
            raise ValueError('The selected IGDB game could not be verified.')
        game_request = GameRequest(request_type='new_game', **snapshot)
        db.session.add(game_request)
        db.session.flush()

    clean_note = ((note or '').strip()[:1000] or None) if settings['allowRequestNotes'] else None
    accepts_any = bool(accept_any_edition and settings['allowRequestAnyEdition'])
    if link:
        link.withdrawn_at = None
        link.satisfied_at = None
        link.satisfied_by_game_uuid = None
        link.requester_note = clean_note
        link.accept_any_edition = accepts_any
    else:
        link = GameRequestUser(
            request_id=game_request.id,
            user_id=user.id,
            requester_note=clean_note,
            accept_any_edition=accepts_any,
        )
        db.session.add(link)
    if game_request.status == 'cancelled':
        game_request.status = 'pending'
        game_request.resolved_at = None
    db.session.commit()
    return game_request, link


def create_update_request(user, game, note=None, target_version=None, reference_url=None):
    settings = get_request_settings()
    if not settings['enableGameRequests']:
        raise ValueError('Game requests are disabled.')

    version_str = (target_version or '').strip()[:100]
    ref_url_str = (reference_url or '').strip()[:500]
    user_note_str = (note or '').strip()[:1000]

    note_parts = []
    if version_str:
        note_parts.append(f"Target Version/Build: {version_str}")
    if ref_url_str:
        note_parts.append(f"Reference: {ref_url_str}")
    if user_note_str:
        note_parts.append(f"Note: {user_note_str}")

    combined_note = "\n".join(note_parts) if note_parts else None

    game_request = db.session.execute(
        select(GameRequest).where(
            GameRequest.source_game_uuid == game.uuid,
            GameRequest.request_type == 'update',
            ~GameRequest.status.in_(RESOLVED_STATUSES)
        )
    ).scalars().first()

    link = None
    if game_request:
        link = db.session.execute(
            select(GameRequestUser).filter_by(request_id=game_request.id, user_id=user.id)
        ).scalars().first()

    if link and link.withdrawn_at is None:
        raise ValueError('You have already requested an update for this game.')

    active_count = db.session.execute(
        select(func.count(GameRequestUser.id)).join(GameRequest).where(
            GameRequestUser.user_id == user.id,
            GameRequestUser.withdrawn_at.is_(None),
            GameRequestUser.satisfied_at.is_(None),
            ~GameRequest.status.in_(RESOLVED_STATUSES),
        )
    ).scalar_one()
    if active_count >= int(settings['maxActiveRequestsPerUser']):
        raise ValueError('You have reached the active game request limit.')

    if not game_request:
        cover_image = game.images.filter_by(image_type='cover').first() if hasattr(game.images, 'filter_by') else None
        raw_cover = cover_image.url if cover_image else game.cover
        cover_url = None
        if raw_cover:
            if raw_cover.startswith(('http://', 'https://', '//')):
                cover_url = raw_cover if not raw_cover.startswith('//') else f'https:{raw_cover}'
            elif raw_cover.startswith('/'):
                cover_url = raw_cover
            else:
                cover_url = f'/static/library/images/{raw_cover}'

        edition_label = f"Update to {version_str}" if version_str else (f"Update for {game.version}" if game.version else "Game Update")

        game_request = GameRequest(
            request_type='update',
            source_game_uuid=game.uuid,
            igdb_id=game.igdb_id,
            parent_igdb_id=game.igdb_id,
            parent_game_name=game.name,
            game_name=game.name,
            edition_name=edition_label,
            cover_url=cover_url,
            summary=game.summary,
            status='pending',
        )
        db.session.add(game_request)
        db.session.flush()

    clean_note = combined_note if settings['allowRequestNotes'] else None
    if link:
        link.withdrawn_at = None
        link.satisfied_at = None
        link.satisfied_by_game_uuid = None
        link.requester_note = clean_note
        link.accept_any_edition = False
    else:
        link = GameRequestUser(
            request_id=game_request.id,
            user_id=user.id,
            requester_note=clean_note,
            accept_any_edition=False,
        )
        db.session.add(link)
    if game_request.status == 'cancelled':
        game_request.status = 'pending'
        game_request.resolved_at = None
    db.session.commit()
    return game_request, link


def withdraw_request(user, request_id):
    link = db.session.execute(
        select(GameRequestUser).filter_by(request_id=request_id, user_id=user.id)
    ).scalars().first()
    if not link or link.withdrawn_at is not None:
        raise ValueError('Request was not found.')
    if link.game_request.status in RESOLVED_STATUSES:
        raise ValueError('Resolved requests cannot be withdrawn.')
    link.withdrawn_at = datetime.now(timezone.utc)
    if not any(
        item.withdrawn_at is None and item.satisfied_at is None
        for item in link.game_request.requesters if item.id != link.id
    ):
        link.game_request.status = 'cancelled'
        link.game_request.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return link.game_request


def update_request_preferences(user, request_id, note=None, accept_any_edition=False):
    """Update the current user's editable preferences for an active request."""
    settings = get_request_settings()
    link = db.session.execute(
        select(GameRequestUser)
        .options(selectinload(GameRequestUser.game_request))
        .filter_by(request_id=request_id, user_id=user.id)
    ).scalars().first()
    if not link or link.withdrawn_at is not None:
        raise ValueError('Request was not found.')
    if link.satisfied_at is not None or link.game_request.status in RESOLVED_STATUSES:
        raise ValueError('Resolved requests cannot be edited.')
    link.requester_note = ((note or '').strip()[:2000] or None) if settings['allowRequestNotes'] else None
    link.accept_any_edition = bool(
        accept_any_edition
        and settings['allowRequestAnyEdition']
        and link.game_request.request_type == 'new_game'
    )
    db.session.commit()
    return link


def update_request_status(game_request, admin, status, public_response=None, internal_note=None, game_uuid=None):
    if status not in REQUEST_STATUSES:
        raise ValueError('Invalid request status.')
    fulfilled_game = None
    if status == 'fulfilled':
        if not game_uuid:
            raise ValueError('A library game is required when fulfilling a request.')
        fulfilled_game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if not fulfilled_game:
            raise ValueError('The selected library game could not be found.')
    previous_status = game_request.status
    previous_game_uuid = game_request.fulfilled_game_uuid
    affected_links = []

    if previous_status == 'fulfilled' and (
        status != 'fulfilled' or previous_game_uuid != (fulfilled_game.uuid if fulfilled_game else None)
    ):
        exact_links = [
            link for link in game_request.requesters
            if link.satisfied_by_game_uuid == previous_game_uuid
        ]
        alternative_links = db.session.execute(
            select(GameRequestUser)
            .join(GameRequest)
            .where(
                GameRequest.parent_igdb_id == game_request.parent_igdb_id,
                GameRequest.id != game_request.id,
                GameRequestUser.accept_any_edition.is_(True),
                GameRequestUser.satisfied_by_game_uuid == previous_game_uuid,
            )
        ).scalars().all()
        for link in exact_links + alternative_links:
            link.satisfied_at = None
            link.satisfied_by_game_uuid = None
            affected_links.append(link)

    game_request.status = status
    game_request.public_response = (public_response or '').strip()[:4000] or None
    game_request.internal_note = (internal_note or '').strip()[:4000] or None
    game_request.fulfilled_game = fulfilled_game
    game_request.handled_by_user_id = admin.id
    game_request.resolved_at = datetime.now(timezone.utc) if status in RESOLVED_STATUSES else None
    if status == 'fulfilled':
        exact_links = [link for link in game_request.requesters if link.withdrawn_at is None]
        alternative_links = db.session.execute(
            select(GameRequestUser)
            .join(GameRequest)
            .where(
                GameRequest.parent_igdb_id == game_request.parent_igdb_id,
                GameRequest.id != game_request.id,
                GameRequestUser.accept_any_edition.is_(True),
                GameRequestUser.withdrawn_at.is_(None),
            )
        ).scalars().all()
        for link in exact_links + alternative_links:
            link.satisfied_at = datetime.now(timezone.utc)
            link.satisfied_by_game_uuid = fulfilled_game.uuid
            if link not in affected_links:
                affected_links.append(link)
    db.session.commit()
    return game_request, affected_links
