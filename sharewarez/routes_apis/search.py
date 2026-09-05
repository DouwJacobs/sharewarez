from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, inspect, literal, or_, select, union
from sqlalchemy.orm import load_only, selectinload

from sharewarez import db
from sharewarez.models import Game, GameIssue, GameRequest, Library, User, UserPreference
from sharewarez.utils.admin_navigation import flatten_admin_navigation
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
    # Rank a bounded union, not every matching full ORM row. GiST KNN scans
    # supply the nearest title/word matches even for very common search terms.
    primary_key = inspect(model).primary_key[0]
    lowered = func.lower(title_column)
    candidates = union(
        select(primary_key).where(document.op('@@')(tsquery)).limit(200),
        select(primary_key).where(lowered.contains(query.lower(), autoescape=True)).limit(200),
        select(primary_key).order_by(lowered.op('<->')(query.lower())).limit(100),
        select(primary_key).order_by(lowered.op('<->>')(query.lower())).limit(100),
        select(primary_key).where(lowered == query.lower()).limit(20),
    ).cte('search_candidates').prefix_with('MATERIALIZED')
    fields = {
        Game: (Game.uuid, Game.name),
        Library: (Library.uuid, Library.name, Library.platform),
        User: (User.name, User.email),
        GameRequest: (GameRequest.game_name, GameRequest.status),
        GameIssue: (GameIssue.title, GameIssue.category, GameIssue.status),
    }
    return (
        select(model, rank)
        .join(candidates, primary_key == candidates.c[0])
        .where(or_(document.op('@@')(tsquery), fuzzy_score >= 0.24,
                   lowered.contains(query.lower(), autoescape=True)))
        .options(load_only(*fields[model]))
        .order_by(rank.desc(), title_column, primary_key)
        .limit(limit)
    )


@apis_bp.route('/global-search')
@login_required
def global_search():
    """Return compact, permission-aware results for the global command palette."""
    query = request.args.get('q', '').strip()
    if len(query) > 100:
        return jsonify({'error': 'Search term too long'}), 400
    preferences = current_user.preferences
    saved_searches = list(preferences.saved_searches or []) if preferences else []
    if len(query) < 2:
        return jsonify({'query': query, 'results': [], 'suggestions': saved_searches})

    results = []
    global_settings = get_global_settings()
    navigation = [
        ('Discover', 'Featured games and personalized rows', '/discover', 'fa-compass', 'home featured'),
        ('Library', 'Browse, filter, and sort games', '/library', 'fa-gamepad', 'games collection'),
        ('My activity', 'Requests, issues, downloads, and replies', '/activity', 'fa-list-check', 'status tracking replies'),
        ('Downloads', 'Manage queued and ready files', '/downloads', 'fa-download', 'files retry cancel'),
        ('Notifications', 'Open the activity inbox', '/notifications', 'fa-bell', 'alerts replies'),
        ('Preferences', 'Appearance, Library, and notification settings', '/settings_panel', 'fa-sliders', 'theme browser alerts'),
        ('Help', 'Search guidance and reporting help', '/help', 'fa-circle-question', 'faq support'),
    ]
    if global_settings.get('enable_game_requests', True):
        navigation.append(('Requests', 'Request a game or update', '/requests', 'fa-paper-plane', 'community igdb'))
    if global_settings.get('enable_game_issues', True):
        navigation.append(('My issues', 'Track reported game problems', '/issues', 'fa-bug', 'report support'))
    lowered = query.lower()
    results.extend({
        'type': 'Go to', 'title': title, 'subtitle': subtitle, 'url': url,
        'icon': icon, 'score': 1.2 if lowered == title.lower() else .65,
    } for title, subtitle, url, icon, keywords in navigation
      if lowered in f'{title} {subtitle} {keywords}'.lower())
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

        issues = db.session.execute(
            _ranked_search(
                GameIssue, GameIssue.title,
                (GameIssue.title, GameIssue.description), query, 6,
            )
        ).all()
        results.extend({
            'type': 'Issue',
            'title': issue.title,
            'subtitle': '{} · {}'.format(
                issue.category.replace('_', ' ').title(),
                issue.status.replace('_', ' ').title(),
            ),
            'url': f'/admin/issues/{issue.id}',
            'icon': 'fa-bug',
            'score': round(float(score), 4),
        } for issue, score in issues)

    libraries = db.session.execute(
        _ranked_search(Library, Library.name, (Library.name, Library.name), query, 5)
    ).all()
    results.extend({
        'type': 'Library', 'title': library.name, 'subtitle': str(library.platform.value),
        'url': f'/library?library_uuid={library.uuid}', 'icon': 'fa-layer-group',
        'score': round(float(score), 4),
    } for library, score in libraries)

    if current_user.role == 'admin':
        users = db.session.execute(
            _ranked_search(User, User.name, (User.name, User.email), query, 5)
        ).all()
        results.extend({
            'type': 'User', 'title': user.name, 'subtitle': user.email,
            'url': '/admin/users', 'icon': 'fa-user', 'score': round(float(score), 4)
        } for user, score in users)
        lowered = query.lower()
        results.extend({
            'type': 'Admin', 'title': item['label'], 'subtitle': item['description'],
            'url': item['url'], 'icon': item['icon'],
            'score': 1.0 if lowered == item['label'].lower() else 0.5,
        } for item in flatten_admin_navigation(global_settings)
          if lowered in f"{item['label']} {item['description']} {item.get('keywords', '')}".lower())

    results.sort(key=lambda item: (-item.get('score', 0), item['title'].lower()))
    return jsonify({'query': query, 'results': results[:20], 'suggestions': saved_searches})


@apis_bp.route('/global-search/saved', methods=['POST', 'DELETE'])
@login_required
def saved_global_searches():
    query = ((request.get_json(silent=True) or {}).get('query') or '').strip()
    if not 2 <= len(query) <= 80:
        return jsonify({'error': 'Saved searches must contain 2 to 80 characters.'}), 400
    preferences = current_user.preferences
    if preferences is None:
        preferences = UserPreference(user_id=current_user.id)
        db.session.add(preferences)
    saved = list(preferences.saved_searches or [])
    if request.method == 'POST':
        saved = [item for item in saved if item.casefold() != query.casefold()]
        saved.insert(0, query)
        saved = saved[:12]
    else:
        saved = [item for item in saved if item.casefold() != query.casefold()]
    preferences.saved_searches = saved
    db.session.commit()
    return jsonify({'saved_searches': saved})
