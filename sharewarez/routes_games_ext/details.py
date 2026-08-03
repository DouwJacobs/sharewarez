import uuid
import os
import re
from flask import render_template, jsonify, abort, request, url_for
from flask_login import login_required, current_user
from sharewarez.forms import CsrfForm
from sharewarez.models import GameUpdate, GameExtra, user_game_status, get_status_info
from sharewarez import db
from sqlalchemy import select, and_
from sharewarez.utils.functions import format_size, sanitize_string_input, get_url_icon
from sharewarez.utils.game_core import get_game_by_uuid
from sharewarez.utils.security import sanitize_path_for_logging
from sharewarez.utils.event_logging import log_system_event
from urllib.parse import urlparse

from . import games_bp


def get_path_size(file_path):
    """Calculate size of a file or directory in bytes."""
    try:
        if os.path.isfile(file_path):
            return os.path.getsize(file_path)
        elif os.path.isdir(file_path):
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(file_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except (OSError, IOError):
                        # Skip files that can't be read
                        pass
            return total_size
    except (OSError, IOError):
        pass
    return 0


def get_safe_back_url():
    """Return a game-browsing referrer, falling back to the library.

    Editing and administration pages are deliberately excluded so visiting a
    game after saving metadata cannot turn the details-page Back button into a
    link back into an editor.
    """
    fallback_url = url_for('library.library')
    if not request.referrer:
        return fallback_url

    referrer = urlparse(request.referrer)
    if referrer.netloc != request.host:
        return fallback_url
    allowed_paths = {'/library', '/discover', '/favorites'}
    if referrer.path not in allowed_paths:
        return fallback_url
    return referrer.path + (f'?{referrer.query}' if referrer.query else '')


@games_bp.route('/game_details/<string:game_uuid>')
@login_required
def game_details(game_uuid):
    log_system_event(
        f"User {current_user.name} requested game details for UUID: {game_uuid[:8]}...",
        event_type='game',
        event_level='debug'
    )
    csrf_form = CsrfForm()
    try:
        valid_uuid = uuid.UUID(game_uuid, version=4)
    except ValueError:
        log_system_event(
            f"Invalid UUID format provided by user {current_user.name}: {game_uuid[:20]}...",
            event_type='security',
            event_level='warning'
        )
        abort(404)

    game = get_game_by_uuid(str(valid_uuid))

    if game:
        # Explicitly load updates and extras
        updates = db.session.execute(
            select(GameUpdate).filter_by(game_uuid=game.uuid).order_by(
                GameUpdate.update_number.asc().nullslast(),
                GameUpdate.release_date.asc().nullslast(),
                GameUpdate.created_at.asc()
            )
        ).scalars().all()
        extras = db.session.execute(select(GameExtra).filter_by(game_uuid=game.uuid)).scalars().all()
        
        # Log successful access for audit trail
        log_system_event(
            f"User {current_user.name} accessed game '{game.name}' with {len(updates)} updates and {len(extras)} extras",
            event_type='game',
            event_level='information'
        )
        
        game_data = {
            "id": game.id,
            "uuid": game.uuid,
            "igdb_id": game.igdb_id,
            "name": game.name,
            "summary": game.summary,
            "storyline": game.storyline,
            "install_instructions": game.install_instructions,
            "version": game.version,
            "aggregated_rating": game.aggregated_rating,
            "aggregated_rating_count": game.aggregated_rating_count,
            "updates": [{
                "id": update.id,
                "display_name": update.title or os.path.basename(update.file_path),
                "version": update.version,
                "update_number": update.update_number,
                "requires_version": update.requires_version,
                "install_instructions": update.install_instructions,
                "changelog": update.changelog,
                "release_date": update.release_date.strftime('%Y-%m-%d') if update.release_date else None,
                "is_cumulative": update.is_cumulative,
                "times_downloaded": update.times_downloaded,
                "created_at": update.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                "nfo_content": update.nfo_content,
                "file_size": format_size(update.size or get_path_size(update.file_path))
            } for update in updates],
            "extras": [{
                "id": extra.id,
                "file_path": extra.file_path,
                "times_downloaded": extra.times_downloaded,
                "created_at": extra.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                "nfo_content": extra.nfo_content,
                "file_size": format_size(get_path_size(extra.file_path))
            } for extra in game.extras],
            "cover": game.cover,
            "first_release_date": game.first_release_date.strftime('%Y-%m-%d') if game.first_release_date else 'Not available',
            "rating": game.rating,
            "rating_count": game.rating_count,
            "slug": game.slug,
            "status": (game.status.value if hasattr(game.status, 'value') else str(game.status)) if game.status else 'Not available',
            "category": (game.category.value if hasattr(game.category, 'value') else str(game.category)) if game.category else 'Not available',
            "total_rating": game.total_rating,
            "total_rating_count": game.total_rating_count,
            "url_igdb": game.url_igdb,
            "url": game.url,
            "video_urls": game.video_urls,
            # full_disk_path removed for security - should not be exposed to client
            "images": [{"id": img.id, "type": img.image_type, "url": img.url} for img in game.images.all()],
            "genres": [genre.name for genre in game.genres],
            "game_modes": [mode.name for mode in game.game_modes],
            "themes": [theme.name for theme in game.themes],
            "platforms": [platform.name for platform in game.platforms],
            "player_perspectives": [perspective.name for perspective in game.player_perspectives],
            "tags": [tag.name for tag in game.tags],
            "developer": game.developer.name if game.developer else 'Not available',
            "publisher": game.publisher.name if game.publisher else 'Not available',
            "multiplayer_modes": [mode.name for mode in game.multiplayer_modes],
            "nfo_content": sanitize_string_input(game.nfo_content, 10000) if game.nfo_content else 'none',
            "size": format_size(game.size if (game.size and game.size > 0) else (get_path_size(game.full_disk_path) if game.full_disk_path else 0)),
            "date_identified": game.date_identified.strftime('%Y-%m-%d %H:%M:%S') if game.date_identified else 'Not available',
            "steam_url": game.steam_url if game.steam_url else 'Not available',
            "times_downloaded": game.times_downloaded,
            "last_updated": game.last_updated.strftime('%Y-%m-%d') if game.last_updated else 'N/A',
            # HowLongToBeat data
            "hltb_id": game.hltb_id,
            "hltb_main_story": game.hltb_main_story,
            "hltb_main_extra": game.hltb_main_extra,
            "hltb_completionist": game.hltb_completionist,
            "hltb_all_styles": game.hltb_all_styles,
            "hltb_last_updated": game.hltb_last_updated
            # Duplicate "updates" array removed - already included above
        }
        
        steam_app_id = None
        if game.steam_url:
            match = re.search(r'/app/(\d+)', game.steam_url)
            if match:
                steam_app_id = match.group(1)

        if not steam_app_id and game.igdb_id:
            from sharewarez.utils.igdb_api import get_steam_app_id_from_igdb
            steam_app_id = get_steam_app_id_from_igdb(game.igdb_id)

        steamdb_patchnotes_url = f'https://steamdb.info/app/{steam_app_id}/patchnotes/' if steam_app_id else None

        # Augment game_data with URLs using smart icon detection
        # IGDB imports can contain duplicate website records. Keep the first
        # occurrence of each destination so the details view never renders the
        # same social/link icon more than once.
        seen_urls = set()
        game_data['urls'] = []
        for game_url in game.urls:
            normalized_url = (game_url.url or '').strip().rstrip('/').casefold()
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            game_data['urls'].append({
                "type": game_url.url_type,
                "url": game_url.url,
                "icon": get_url_icon(game_url.url_type, game_url.url)
            })

        # Inject Steam URL if present on game model or resolved via Steam App ID
        steam_target_url = game.steam_url or (f"https://store.steampowered.com/app/{steam_app_id}/" if steam_app_id else None)
        if steam_target_url:
            norm_steam_url = steam_target_url.strip().rstrip('/').casefold()
            if norm_steam_url not in seen_urls:
                seen_urls.add(norm_steam_url)
                game_data['urls'].insert(0, {
                    "type": "steam",
                    "url": steam_target_url,
                    "icon": "fa-brands fa-steam"
                })
        
        library_uuid = game.library_uuid
        
        # Calculate if the game is in current user's favorites
        current_user_id = current_user.id if current_user.is_authenticated else None
        is_favorite = current_user_id in [user.id for user in game.favorited_by] if current_user_id else False

        # Get user's completion status for this game
        user_status = None
        status_icon = 'fa-circle'
        status_label = 'No Status'

        if current_user_id:
            status_row = db.session.execute(
                select(user_game_status.c.status).where(
                    and_(
                        user_game_status.c.user_id == current_user_id,
                        user_game_status.c.game_uuid == game.uuid
                    )
                )
            ).first()

            if status_row:
                user_status = status_row[0]
                status_info = get_status_info(user_status)
                status_icon = status_info['icon']
                status_label = status_info['label']
            else:
                status_info = get_status_info(None)
                status_icon = status_info['icon']
                status_label = status_info['label']

        has_pending_update_request = False
        if current_user_id:
            from sharewarez.models import GameRequest, GameRequestUser
            from sharewarez.utils.game_requests import RESOLVED_STATUSES
            req_link = db.session.execute(
                select(GameRequestUser)
                .join(GameRequest)
                .where(
                    GameRequest.source_game_uuid == game.uuid,
                    GameRequest.request_type == 'update',
                    GameRequestUser.user_id == current_user_id,
                    GameRequestUser.withdrawn_at.is_(None),
                    GameRequestUser.satisfied_at.is_(None),
                    ~GameRequest.status.in_(RESOLVED_STATUSES)
                )
            ).scalars().first()
            has_pending_update_request = req_link is not None

        return render_template(
            'games/game_details.html',
            game=game_data,
            form=csrf_form,
            library_uuid=library_uuid,
            is_admin=current_user.role == 'admin',
            is_favorite=is_favorite,
            user_status=user_status,
            status_icon=status_icon,
            status_label=status_label,
            has_pending_update_request=has_pending_update_request,
            steamdb_patchnotes_url=steamdb_patchnotes_url,
            back_url=get_safe_back_url()
        )
    else:
        log_system_event(
            f"User {current_user.name} attempted to access non-existent game UUID: {game_uuid[:8]}...",
            event_type='security',
            event_level='warning'
        )
        return jsonify({"error": "Game not found"}), 404


@games_bp.route('/game/<game_uuid>/local_image/<image_type>')
@login_required
def serve_local_image(game_uuid, image_type):
    """
    Serve local image file from game folder.

    This route serves local cover.jpg or screenshot-N.jpg files
    that are stored alongside game files.

    Security: Validates game exists and path is safe before serving.
    """
    from flask import send_file, current_app, request
    from sharewarez.models import Game
    from sharewarez.utils.local_metadata import get_local_cover_path, get_local_screenshots
    from sharewarez.utils.security import is_safe_path, get_allowed_base_directories
    import mimetypes

    try:
        # Validate UUID format
        valid_uuid = uuid.UUID(game_uuid, version=4)
    except ValueError:
        log_system_event(
            f"User {current_user.name} attempted to serve local image with invalid UUID: {game_uuid}",
            event_type='security',
            event_level='warning'
        )
        abort(400, "Invalid game UUID")

    # Get game from database
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
    if not game:
        log_system_event(
            f"User {current_user.name} attempted to serve local image for non-existent game: {game_uuid}",
            event_type='security',
            event_level='warning'
        )
        abort(404, "Game not found")

    # Security check
    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        log_system_event(
            f"Server configuration error: No allowed base directories configured",
            event_type='security',
            event_level='error'
        )
        abort(500, "Server configuration error")

    is_safe, error_message = is_safe_path(game.full_disk_path, allowed_bases)
    if not is_safe:
        log_system_event(
            f"Security: User {current_user.name} attempted access to unsafe path {sanitize_path_for_logging(game.full_disk_path)}: {error_message}",
            event_type='security',
            event_level='warning'
        )
        abort(403, "Access denied")

    # Get local image path
    image_path = None
    if image_type == 'cover':
        image_path = get_local_cover_path(game.full_disk_path)
    elif image_type == 'screenshot':
        index = request.args.get('index', 0, type=int)
        screenshots = get_local_screenshots(game.full_disk_path)
        if 0 <= index < len(screenshots):
            image_path = screenshots[index]
    else:
        log_system_event(
            f"User {current_user.name} requested invalid image type: {image_type}",
            event_type='security',
            event_level='warning'
        )
        abort(400, "Invalid image type")

    if not image_path or not os.path.exists(image_path):
        log_system_event(
            f"User {current_user.name} requested local image that doesn't exist: {image_type} for game {game.name}",
            event_type='game',
            event_level='debug'
        )
        abort(404, "Image not found")

    # Detect MIME type based on file extension
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        # Default to jpeg if we can't detect
        mime_type = 'image/jpeg'

    # Serve the image file
    log_system_event(
        f"Serving local {image_type} image for game '{game.name}' to user {current_user.name}",
        event_type='game',
        event_level='debug'
    )
    return send_file(image_path, mimetype=mime_type)
