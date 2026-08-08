from flask import Blueprint, render_template, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sharewarez.utils.functions import format_size
from sharewarez.utils.processors import get_loc
from sharewarez.models import Game, Library, user_favorites, DiscoverySection
from sharewarez import db
from flask_login import login_required
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
    
    def fetch_game_details(games_statement, limit=8):
        """Fetch a bounded section without per-game relationship queries."""
        games = db.session.execute(
            games_statement.options(selectinload(Game.genres)).limit(limit)
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
            cover_url = covers.get(game.uuid, url_for('static', filename='newstyle/default_cover.jpg'))
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
                # Optionally include library information here
            })
        return game_details

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

    return render_template('games/discover.html',
                           visible_sections=visible_sections,
                           section_data=section_data,
                           loc=page_loc)
