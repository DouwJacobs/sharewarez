from flask import g, jsonify, request
from sqlalchemy import func, select

from sharewarez import db
from sharewarez.models import DownloadRequest, Game, Library
from sharewarez.utils.api_tokens import require_api_scope

from . import apis_bp


def _iso(value):
    return value.isoformat() if value else None


def _pagination_args():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 25))
    except (TypeError, ValueError):
        raise ValueError('page and per_page must be integers') from None
    if page < 1 or per_page < 1 or per_page > 100:
        raise ValueError('page must be positive and per_page must be between 1 and 100')
    return page, per_page


def _page_payload(items, page, per_page, total):
    return {
        'data': items,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
        },
    }


def _game_payload(game, detailed=False):
    payload = {
        'uuid': game.uuid,
        'name': game.name,
        'slug': game.slug,
        'library_uuid': game.library_uuid,
        'cover': game.cover,
        'release_date': _iso(game.first_release_date),
        'category': game.category.value if game.category else None,
        'status': game.status.value if game.status else None,
        'rating': game.rating,
        'size_bytes': game.size,
        'version': game.version,
        'last_updated': _iso(game.last_updated),
    }
    if detailed:
        from sharewarez.utils.game_relationships import serialize_game_relationships
        payload.update({
            'summary': game.summary,
            'developer': game.developer.name if game.developer else None,
            'publisher': game.publisher.name if game.publisher else None,
            'genres': sorted(item.name for item in game.genres),
            'platforms': sorted(item.name for item in game.platforms),
            'themes': sorted(item.name for item in game.themes),
            'game_modes': sorted(item.name for item in game.game_modes),
            'series': sorted(group.name for group in game.groups if group.group_type == 'series'),
            'franchises': sorted(group.name for group in game.groups if group.group_type == 'franchise'),
            'relationships': serialize_game_relationships(game),
        })
    return payload


@apis_bp.get('/v1/profile')
@require_api_scope('profile:read')
def public_profile():
    user = g.api_user
    return jsonify({'data': {
        'id': user.user_id,
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'member_since': _iso(user.created),
    }})


@apis_bp.get('/v1/libraries')
@require_api_scope('library:read')
def public_libraries():
    game_counts = (
        select(Game.library_uuid, func.count(Game.id).label('game_count'))
        .group_by(Game.library_uuid)
        .subquery()
    )
    rows = db.session.execute(
        select(Library, func.coalesce(game_counts.c.game_count, 0))
        .outerjoin(game_counts, game_counts.c.library_uuid == Library.uuid)
        .order_by(Library.display_order, Library.name)
    ).all()
    return jsonify({'data': [{
        'uuid': library.uuid,
        'name': library.name,
        'platform': library.platform.value,
        'image_url': library.image_url,
        'game_count': count,
    } for library, count in rows]})


@apis_bp.get('/v1/games')
@require_api_scope('library:read')
def public_games():
    try:
        page, per_page = _pagination_args()
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    query = select(Game)
    count_query = select(func.count()).select_from(Game)
    library_uuid = (request.args.get('library_uuid') or '').strip()
    search = (request.args.get('q') or '').strip()
    if library_uuid:
        query = query.where(Game.library_uuid == library_uuid)
        count_query = count_query.where(Game.library_uuid == library_uuid)
    if search:
        pattern = f'%{search}%'
        query = query.where(Game.name.ilike(pattern))
        count_query = count_query.where(Game.name.ilike(pattern))

    total = db.session.scalar(count_query) or 0
    games = db.session.execute(
        query.order_by(Game.name, Game.uuid).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    return jsonify(_page_payload([_game_payload(game) for game in games], page, per_page, total))


@apis_bp.get('/v1/games/<string:game_uuid>')
@require_api_scope('library:read')
def public_game(game_uuid):
    game = db.session.execute(select(Game).where(Game.uuid == game_uuid)).scalar_one_or_none()
    if game is None:
        return jsonify({'error': 'Game not found'}), 404
    return jsonify({'data': _game_payload(game, detailed=True)})


@apis_bp.get('/v1/downloads')
@require_api_scope('downloads:read')
def public_downloads():
    try:
        page, per_page = _pagination_args()
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    query = select(DownloadRequest).where(DownloadRequest.user_id == g.api_user.id)
    count_query = select(func.count()).select_from(DownloadRequest).where(
        DownloadRequest.user_id == g.api_user.id
    )
    status = (request.args.get('status') or '').strip()
    if status:
        query = query.where(DownloadRequest.status == status)
        count_query = count_query.where(DownloadRequest.status == status)

    total = db.session.scalar(count_query) or 0
    downloads = db.session.execute(
        query.order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()
    items = [{
        'id': item.id,
        'game_uuid': item.game_uuid,
        'game_name': item.game.name if item.game else None,
        'content_type': item.content_type,
        'content_title': item.content_title,
        'status': item.status,
        'size_bytes': int(item.download_size or 0),
        'requested_at': _iso(item.request_time),
        'completed_at': _iso(item.completion_time),
        'expires_at': _iso(item.expires_at),
    } for item in downloads]
    return jsonify(_page_payload(items, page, per_page, total))
