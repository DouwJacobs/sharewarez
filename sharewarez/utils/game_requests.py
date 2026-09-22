from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import joinedload, selectinload

from sharewarez import db
from sharewarez.models import (
    Game,
    GameExternalIdentity,
    GameRequest,
    GameRequestUser,
    GlobalSettings,
)
from sharewarez.utils.igdb_api import make_igdb_api_request
from sharewarez.utils.metadata_provider_igdb import (
    IGDBMetadataProvider,
    normalize_igdb_game,
)
from sharewarez.utils.metadata_providers import build_metadata_provider_registry


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


def _igdb_provider():
    # Keep the request callable injected here so existing callers and tests can
    # replace the transport without bypassing the provider boundary.
    return IGDBMetadataProvider(request=make_igdb_api_request)


def _metadata_registry():
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalar_one_or_none()
    if settings is None:
        return None
    return build_metadata_provider_registry(
        settings,
        igdb_request=make_igdb_api_request,
    )


def fetch_igdb_game(igdb_id):
    return _igdb_provider().fetch_game(igdb_id)


def search_metadata_request_games(term):
    registry = _metadata_registry()
    if registry is None or not registry.providers:
        return [], 'No metadata providers are configured.'
    cache_key = (registry.order, term.strip().casefold())
    now = monotonic()
    with _search_cache_lock:
        cached = _search_cache.get(cache_key)
        if cached and cached[0] > now:
            return deepcopy(cached[1]), None
    outcome = registry.search_games(term)
    results = outcome.results
    if not results and outcome.error:
        return [], outcome.error
    with _search_cache_lock:
        expired = [key for key, value in _search_cache.items() if value[0] <= now]
        for key in expired:
            _search_cache.pop(key, None)
        if len(_search_cache) >= _SEARCH_CACHE_MAX_ENTRIES:
            _search_cache.pop(next(iter(_search_cache)))
        _search_cache[cache_key] = (now + _SEARCH_CACHE_TTL_SECONDS, deepcopy(results))
    return results, None


def search_igdb_games(term):
    """Compatibility alias for provider-neutral request discovery."""
    return search_metadata_request_games(term)


def fetch_related_editions(igdb_id):
    return _igdb_provider().fetch_related_editions(igdb_id)


def fetch_metadata_game(provider, external_id):
    provider_name = str(provider).strip().lower()
    if provider_name == 'igdb':
        return fetch_igdb_game(int(external_id))
    registry = _metadata_registry()
    adapter = registry.providers.get(provider_name) if registry else None
    return adapter.fetch_game(external_id) if adapter else None


def enrich_request_search(results, user_id):
    keys = [
        (str(item.get('provider') or 'igdb'), str(item.get('provider_game_id') or item.get('igdb_id')))
        for item in results
        if item.get('provider_game_id') is not None or item.get('igdb_id') is not None
    ]
    if not keys:
        return results
    identities = db.session.execute(
        select(GameExternalIdentity)
        .options(joinedload(GameExternalIdentity.game))
        .where(tuple_(GameExternalIdentity.provider, GameExternalIdentity.external_id).in_(keys))
    ).scalars().all()
    requests = db.session.execute(
        select(GameRequest)
        .options(selectinload(GameRequest.requesters))
        .where(tuple_(GameRequest.metadata_provider, GameRequest.provider_game_id).in_(keys))
    ).scalars().all()
    games_by_identity = {
        (item.provider, item.external_id): item.game for item in identities
    }
    requests_by_identity = {
        (item.metadata_provider, item.provider_game_id): item for item in requests
    }
    igdb_ids = [int(external_id) for provider, external_id in keys if provider == 'igdb' and external_id.isdigit()]
    if igdb_ids:
        for game in db.session.execute(select(Game).where(Game.igdb_id.in_(igdb_ids))).scalars():
            games_by_identity.setdefault(('igdb', str(game.igdb_id)), game)
        legacy_requests = db.session.execute(
            select(GameRequest)
            .options(selectinload(GameRequest.requesters))
            .where(GameRequest.igdb_id.in_(igdb_ids))
        ).scalars().all()
        for game_request in legacy_requests:
            requests_by_identity.setdefault(('igdb', str(game_request.igdb_id)), game_request)
    for item in results:
        key = (
            str(item.get('provider') or 'igdb'),
            str(item.get('provider_game_id') or item.get('igdb_id')),
        )
        local_game = games_by_identity.get(key)
        game_request = requests_by_identity.get(key)
        item['available_game_uuid'] = local_game.uuid if local_game else None
        item['request_id'] = game_request.id if game_request else None
        item['request_status'] = game_request.status if game_request else None
        item['can_join_request'] = bool(
            game_request and game_request.status in {'pending', 'reviewing', 'planned'}
        )
        item['requester_count'] = len(game_request.interested_requesters) if game_request else 0
        item['requested_by_user'] = bool(game_request and any(link.user_id == user_id and link.withdrawn_at is None for link in game_request.requesters))
    return results


def _existing_game(provider, external_id):
    identity = db.session.execute(
        select(GameExternalIdentity)
        .options(joinedload(GameExternalIdentity.game))
        .where(
            GameExternalIdentity.provider == provider,
            GameExternalIdentity.external_id == external_id,
        )
    ).scalar_one_or_none()
    if identity:
        return identity.game
    if provider == 'igdb' and external_id.isdigit():
        return db.session.execute(
            select(Game).filter_by(igdb_id=int(external_id))
        ).scalar_one_or_none()
    return None


def find_game_request(provider, external_id):
    filters = [
        (
            GameRequest.metadata_provider == provider,
            GameRequest.provider_game_id == external_id,
        ),
    ]
    conditions = [left & right for left, right in filters]
    if provider == 'igdb' and external_id.isdigit():
        conditions.append(GameRequest.igdb_id == int(external_id))
    return db.session.execute(
        select(GameRequest).where(
            GameRequest.request_type == 'new_game',
            or_(*conditions),
        )
    ).scalars().first()


def _request_snapshot(snapshot, provider, external_id):
    provider_parent_id = str(
        snapshot.get('provider_parent_id')
        or snapshot.get('parent_igdb_id')
        or external_id
    )
    values = {
        'metadata_provider': provider,
        'provider_game_id': external_id,
        'provider_parent_id': provider_parent_id,
        'provider_url': snapshot.get('provider_url'),
        'provider_attribution': snapshot.get('attribution'),
        'parent_game_name': snapshot.get('parent_game_name'),
        'game_name': snapshot.get('game_name'),
        'edition_name': snapshot.get('edition_name'),
        'cover_url': snapshot.get('cover_url'),
        'summary': snapshot.get('summary'),
        'platforms': snapshot.get('platforms'),
        'first_release_date': snapshot.get('first_release_date'),
    }
    if provider == 'igdb' and external_id.isdigit():
        values['igdb_id'] = int(external_id)
        values['parent_igdb_id'] = int(provider_parent_id)
    return values


def create_or_join_request(user, igdb_id, note=None, accept_any_edition=False):
    """Compatibility wrapper for existing IGDB callers."""
    return create_or_join_metadata_request(
        user,
        'igdb',
        str(int(igdb_id)),
        note,
        accept_any_edition,
    )


def create_or_join_metadata_request(
    user,
    provider,
    external_id,
    note=None,
    accept_any_edition=False,
):
    provider = str(provider).strip().lower()
    external_id = str(external_id).strip()
    if provider not in {'igdb', 'rawg'} or not external_id or len(external_id) > 255:
        raise ValueError('A valid metadata provider game is required.')
    if provider == 'igdb' and not external_id.isdigit():
        raise ValueError('A valid IGDB game is required.')
    settings = get_request_settings()
    if not settings['enableGameRequests']:
        raise ValueError('Game requests are disabled.')
    if _existing_game(provider, external_id):
        raise ValueError('This game is already available in the library.')

    game_request = find_game_request(provider, external_id)
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
        snapshot = fetch_metadata_game(provider, external_id)
        if not snapshot or not snapshot['game_name']:
            raise ValueError(f'The selected {provider.upper()} game could not be verified.')
        game_request = GameRequest(
            request_type='new_game',
            **_request_snapshot(snapshot, provider, external_id),
        )
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
    if status == 'fulfilled' and game_request.request_type != 'issue':
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
    if status == 'fulfilled' and game_request.request_type == 'issue':
        for link in game_request.requesters:
            if link.withdrawn_at is None:
                link.satisfied_at = datetime.now(timezone.utc)
                affected_links.append(link)
    elif status == 'fulfilled':
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
