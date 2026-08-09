from flask import Blueprint, render_template, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sharewarez.utils.functions import format_size
from sharewarez.utils.processors import get_loc
from sharewarez.models import (
    DiscoverySection,
    Collection,
    CollectionGame,
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
from sharewarez.utils.collections import collection_visibility_clause, evaluate_smart_collection

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
    curated_collections = db.session.execute(
        select(Collection)
        .where(
            (Collection.is_featured.is_(True)) | (Collection.show_on_discover.is_(True)),
            collection_visibility_clause(current_user),
        )
        .order_by(Collection.is_featured.desc(), Collection.display_order, Collection.name)
    ).scalars().all()

    collection_games = {collection.id: [] for collection in curated_collections}
    if curated_collections:
        collection_ids = [collection.id for collection in curated_collections if not collection.is_smart]
        ranked_links = select(
            CollectionGame.collection_id,
            CollectionGame.game_uuid,
            CollectionGame.display_order,
            func.row_number().over(
                partition_by=CollectionGame.collection_id,
                order_by=CollectionGame.display_order,
            ).label('row_number'),
        ).where(CollectionGame.collection_id.in_(collection_ids)).subquery()
        if collection_ids:
            curated_rows = db.session.execute(
                select(ranked_links.c.collection_id, Game)
                .join(Game, Game.uuid == ranked_links.c.game_uuid)
                .options(selectinload(Game.genres), selectinload(Game.library))
                .where(ranked_links.c.row_number <= 12)
                .order_by(ranked_links.c.collection_id, ranked_links.c.display_order)
            ).all()
            for collection_id, game in curated_rows:
                collection_games[collection_id].append(game)
        for collection in curated_collections:
            if collection.is_smart:
                collection_games[collection.id] = evaluate_smart_collection(collection, limit=12)

    curated_games = list({
        game.uuid: game
        for games in collection_games.values()
        for game in games
    }.values())
    seen_curated_uuids = {game.uuid for game in curated_games}

    curated_covers = {}
    curated_screenshots = {}
    if seen_curated_uuids:
        for game_uuid, image_type, url in db.session.execute(
            select(Image.game_uuid, Image.image_type, Image.url)
            .where(
                Image.game_uuid.in_(seen_curated_uuids),
                Image.image_type.in_(('cover', 'screenshot')),
            )
            .order_by(Image.id)
        ).all():
            target = curated_covers if image_type == 'cover' else curated_screenshots
            target.setdefault(game_uuid, url)

    curated_details = {}
    for game in curated_games:
        curated_details[game.uuid] = {
            'id': game.id,
            'uuid': game.uuid,
            'name': game.name,
            'cover_url': image_url(curated_covers.get(game.uuid)),
            'summary': game.summary,
            'url': game.url,
            'size': format_size(game.size),
            'genres': [genre.name for genre in game.genres],
            'first_release_date': game.first_release_date.strftime('%Y-%m-%d') if game.first_release_date else 'Not available',
            'rating': round(game.rating) if game.rating is not None else None,
            'library_name': game.library.name if game.library else None,
        }

    collection_rows = []
    featured_games = []
    for collection in curated_collections:
        games = [curated_details[game.uuid] for game in collection_games[collection.id] if game.uuid in curated_details]
        if collection.is_featured:
            featured_games = games[:8]
        elif collection.show_on_discover and games:
            collection_rows.append({'name': collection.name, 'slug': collection.slug, 'description': collection.description, 'artwork_url': collection.artwork_url, 'group_name': collection.parent.name if collection.parent else None, 'games': games})

    if not featured_games and featured_candidates:
        featured_games = [featured_candidates[0]]
    for game in featured_games:
        game['backdrop_url'] = image_url(curated_screenshots.get(game['uuid']) or game['cover_url'])

    return render_template('games/discover.html',
                           visible_sections=visible_sections,
                           section_data=section_data,
                           featured_games=featured_games,
                           collection_rows=collection_rows,
                           continue_games=continue_games,
                           library_stats=library_stats,
                           recent_downloads=recent_downloads,
                           recent_requests=recent_requests,
                           loc=page_loc)
