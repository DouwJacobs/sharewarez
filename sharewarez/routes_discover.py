from flask import Blueprint, render_template, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sharewarez.utils.functions import format_size
from sharewarez.utils.processors import get_loc
from sharewarez.models import (
    DiscoverySection,
    DownloadRequest,
    Game,
    GameRequest,
    GameRequestUser,
    Library,
    user_favorites,
    user_game_status,
)
from sharewarez import db
from flask_login import current_user, login_required
from sharewarez.models import Image
from sharewarez.utils.processors import get_global_settings
from sharewarez import cache

discover_bp = Blueprint('discover', __name__)

@discover_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Context processor to inject global settings into templates"""
    return get_global_settings()


@discover_bp.route('/discover')
@login_required
def discover():
    page_loc = get_loc("discover")
    
    # Get visible sections in correct order
    visible_sections = db.session.execute(select(DiscoverySection).filter_by(is_visible=True).order_by(DiscoverySection.display_order)).scalars().all()
    
    def image_url(path):
        if not path:
            return url_for('static', filename='newstyle/default_cover.jpg')
        if path.startswith(('http://', 'https://', '//', '/')):
            return path
        return url_for('static', filename=f'library/images/{path}')

    def fetch_game_details(games_statement, limit=10):
        """Fetch a bounded section without per-game relationship queries."""
        games = db.session.execute(
            games_statement.options(selectinload(Game.genres), selectinload(Game.library)).limit(limit)
        ).scalars().all()

        game_uuids = [game.uuid for game in games]
        covers = {}
        if game_uuids:
            cover_images = db.session.execute(
                select(Image)
                .where(Image.game_uuid.in_(game_uuids), Image.image_type == 'cover')
                .order_by(Image.id)
            ).scalars().all()
            for image in cover_images:
                covers.setdefault(image.game_uuid, image.url)

        game_details = []
        for game in games:
            cover_url = image_url(covers.get(game.uuid))
            game_details.append({
                'id': game.id,
                'uuid': game.uuid,
                'name': game.name,
                'cover_url': cover_url,
                'summary': game.summary,
                'url': game.url,
                'size': format_size(game.size),
                'genres': [genre.name for genre in game.genres],
                'first_release_date': game.first_release_date.strftime('%Y-%m-%d') if game.first_release_date else 'Not available',
                'rating': round(game.rating) if game.rating is not None else None,
                'library_name': game.library.name if game.library else None,
                # Optionally include library information here
            })
        return game_details

    # Personal activity is deliberately bounded so the landing page remains
    # fast even for large libraries and long-lived servers.
    continue_games = fetch_game_details(
        select(Game)
        .join(user_game_status, user_game_status.c.game_uuid == Game.uuid)
        .where(
            user_game_status.c.user_id == current_user.id,
            user_game_status.c.status == 'unfinished',
        )
        .order_by(user_game_status.c.updated_at.desc()),
        limit=6,
    )

    status_counts = dict(db.session.execute(
        select(user_game_status.c.status, func.count())
        .where(user_game_status.c.user_id == current_user.id)
        .group_by(user_game_status.c.status)
    ).all())
    library_stats = {
        'games': db.session.execute(select(func.count(Game.id))).scalar_one(),
        'favorites': db.session.execute(
            select(func.count()).select_from(user_favorites).where(user_favorites.c.user_id == current_user.id)
        ).scalar_one(),
        'playing': status_counts.get('unfinished', 0),
        'completed': status_counts.get('completed', 0) + status_counts.get('beaten', 0),
    }

    recent_downloads = db.session.execute(
        select(DownloadRequest)
        .options(selectinload(DownloadRequest.game))
        .where(DownloadRequest.user_id == current_user.id)
        .order_by(DownloadRequest.request_time.desc())
        .limit(3)
    ).scalars().all()
    recent_requests = db.session.execute(
        select(GameRequestUser)
        .options(selectinload(GameRequestUser.game_request))
        .where(GameRequestUser.user_id == current_user.id, GameRequestUser.withdrawn_at.is_(None))
        .order_by(GameRequestUser.created_at.desc())
        .limit(3)
    ).scalars().all()

    # Create a dictionary to store section data
    section_data = {}
    
    for section in visible_sections:
        if section.identifier == 'libraries':
            libraries = db.session.execute(select(Library)).scalars().all()
            section_data['libraries'] = [{
                'uuid': lib.uuid,
                'name': lib.name,
                'image_url': lib.image_url
            } for lib in libraries]
        elif section.identifier == 'latest_games':
            section_data['latest_games'] = fetch_game_details(select(Game).order_by(Game.date_created.desc()))
        elif section.identifier == 'most_downloaded':
            section_data['most_downloaded'] = fetch_game_details(
                select(Game).where(Game.times_downloaded > 0).order_by(Game.times_downloaded.desc())
            )
        elif section.identifier == 'highest_rated':
            section_data['highest_rated'] = fetch_game_details(
                select(Game).where(Game.rating.isnot(None)).order_by(Game.rating.desc())
            )
        elif section.identifier == 'last_updated':
            section_data['last_updated'] = fetch_game_details(
                select(Game).where(Game.last_updated.isnot(None)).order_by(Game.last_updated.desc())
            )
        elif section.identifier == 'most_favorited':
            section_data['most_favorited'] = fetch_game_details(
                select(Game, func.count(user_favorites.c.user_id).label('favorite_count'))
                .join(user_favorites)
                .group_by(Game)
                .order_by(func.count(user_favorites.c.user_id).desc())
            )

    featured_candidates = section_data.get('highest_rated') or section_data.get('latest_games') or []
    featured_game = featured_candidates[0] if featured_candidates else None
    if featured_game:
        backdrop = db.session.execute(
            select(Image.url)
            .where(Image.game_uuid == featured_game['uuid'], Image.image_type == 'screenshot')
            .order_by(Image.id)
            .limit(1)
        ).scalar_one_or_none()
        featured_game['backdrop_url'] = image_url(backdrop or featured_game['cover_url'])

    return render_template('games/discover.html',
                           visible_sections=visible_sections,
                           section_data=section_data,
                           featured_game=featured_game,
                           continue_games=continue_games,
                           library_stats=library_stats,
                           recent_downloads=recent_downloads,
                           recent_requests=recent_requests,
                           loc=page_loc)
