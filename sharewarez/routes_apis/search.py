from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import Game, Library, User
from sharewarez.utils.processors import get_global_settings
from . import apis_bp


@apis_bp.route('/global-search')
@login_required
def global_search():
    """Return compact, permission-aware results for the global command palette."""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'query': query, 'results': []})

    pattern = f'%{query}%'
    results = []
    games = db.session.execute(
        select(Game).where(Game.name.ilike(pattern)).order_by(Game.name).limit(8)
    ).scalars().all()
    results.extend({
        'type': 'Game', 'title': game.name, 'subtitle': 'Game details',
        'url': f'/game_details/{game.uuid}', 'icon': 'fa-gamepad'
    } for game in games)

    libraries = db.session.execute(
        select(Library).where(Library.name.ilike(pattern)).order_by(Library.name).limit(5)
    ).scalars().all()
    results.extend({
        'type': 'Library', 'title': library.name, 'subtitle': str(library.platform.value),
        'url': f'/library?library_uuid={library.uuid}', 'icon': 'fa-layer-group'
    } for library in libraries)

    if current_user.role == 'admin':
        site_title = get_global_settings()['site_title']
        users = db.session.execute(
            select(User).where(User.name.ilike(pattern)).order_by(User.name).limit(5)
        ).scalars().all()
        results.extend({
            'type': 'User', 'title': user.name, 'subtitle': user.email,
            'url': '/admin/users', 'icon': 'fa-user'
        } for user in users)
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
            'url': url, 'icon': icon
        } for title, subtitle, url, icon in settings_pages if lowered in f'{title} {subtitle}'.lower())

    return jsonify({'query': query, 'results': results[:20]})
