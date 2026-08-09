from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import selectinload

from sharewarez import db
from sharewarez.models import Game, GameRequest, Library, User
from sharewarez.utils.processors import get_global_settings
from . import apis_bp


def _ranked_search(model, title_column, text_columns, query, limit):
    document = func.to_tsvector(
        'simple',
        func.coalesce(text_columns[0], '') + literal(' ') + func.coalesce(text_columns[1], ''),
    )
    tsquery = func.websearch_to_tsquery('simple', query)
    fuzzy_score = func.greatest(
        func.similarity(func.lower(title_column), query.lower()),
        func.word_similarity(query.lower(), func.lower(title_column)),
    )
    rank = (func.ts_rank_cd(document, tsquery) + fuzzy_score).label('search_rank')
    return (
        select(model, rank)
        .where(or_(document.op('@@')(tsquery), fuzzy_score >= 0.24, title_column.ilike(f'%{query}%')))
        .order_by(rank.desc(), title_column)
        .limit(limit)
    )


@apis_bp.route('/global-search')
@login_required
def global_search():
    """Return compact, permission-aware results for the global command palette."""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'query': query, 'results': []})

    results = []
    games = db.session.execute(
        _ranked_search(Game, Game.name, (Game.name, Game.summary), query, 8)
    ).all()
    results.extend({
        'type': 'Game', 'title': game.name, 'subtitle': 'Game details',
        'url': f'/game_details/{game.uuid}', 'icon': 'fa-gamepad', 'score': round(float(score), 4)
    } for game, score in games)

    if current_user.role == 'admin':
        requests = db.session.execute(
            _ranked_search(
                GameRequest, GameRequest.game_name,
                (GameRequest.game_name, GameRequest.parent_game_name), query, 6,
            )
            .options(selectinload(GameRequest.requesters))
        ).all()
        results.extend({
            'type': 'Request',
            'title': game_request.game_name,
            'subtitle': '{} · {} interested'.format(
                game_request.status.replace('_', ' ').title(),
                len(game_request.interested_requesters),
            ),
            'url': f'/admin/game-requests/{game_request.id}',
            'icon': 'fa-paper-plane',
            'score': round(float(score), 4),
        } for game_request, score in requests)

    libraries = db.session.execute(
        _ranked_search(Library, Library.name, (Library.name, Library.name), query, 5)
    ).all()
    results.extend({
        'type': 'Library', 'title': library.name, 'subtitle': str(library.platform.value),
        'url': f'/library?library_uuid={library.uuid}', 'icon': 'fa-layer-group',
        'score': round(float(score), 4),
    } for library, score in libraries)

    if current_user.role == 'admin':
        site_title = get_global_settings()['site_title']
        users = db.session.execute(
            _ranked_search(User, User.name, (User.name, User.email), query, 5)
        ).all()
        results.extend({
            'type': 'User', 'title': user.name, 'subtitle': user.email,
            'url': '/admin/users', 'icon': 'fa-user', 'score': round(float(score), 4)
        } for user, score in users)
        settings_pages = [
            ('Downloads', 'Manage download requests', '/admin/manage-downloads', 'fa-download'),
            ('Libraries', 'Manage game libraries', '/admin/libraries', 'fa-layer-group'),
            ('Branding', f'Configure {site_title} title and logo', '/admin/branding', 'fa-signature'),
            ('Server settings', f'Configure {site_title}', '/admin/settings', 'fa-sliders'),
            ('System logs', 'Review audit and system events', '/admin/system_logs', 'fa-clipboard-list'),
            ('Users', 'Manage user accounts', '/admin/users', 'fa-users'),
        ]
        lowered = query.lower()
        results.extend({
            'type': 'Setting', 'title': title, 'subtitle': subtitle,
            'url': url, 'icon': icon, 'score': 1.0 if lowered == title.lower() else 0.5,
        } for title, subtitle, url, icon in settings_pages if lowered in f'{title} {subtitle}'.lower())

    results.sort(key=lambda item: (-item.get('score', 0), item['title'].lower()))
    return jsonify({'query': query, 'results': results[:20]})
