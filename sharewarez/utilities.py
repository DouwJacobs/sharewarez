import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from flask import current_app, flash, redirect, url_for, session, copy_current_request_context
from sharewarez.utils.functions import (
    load_scanning_filter_patterns, get_folder_size_in_bytes_updates,
    read_first_nfo_content,
)
from sharewarez.models import (
    Game, Library, AllowedFileType, ScanJob, GlobalSettings, UnmatchedFolder,
    Genre, Theme, GameMode, Platform, PlayerPerspective,
)
from sharewarez.metadata_files import DEFAULT_LOCAL_METADATA_FILENAME
from sharewarez import db
from sharewarez.utils.game_core import (
    remove_from_lib, fetch_game_by_igdb_id, enumerate_companies,
    get_or_create_entity, category_mapping, status_mapping,
)
from sharewarez.utils.gamenames import get_game_names_from_folder, get_game_names_from_files
from sharewarez.utils.scanning import process_game_with_fallback, process_game_updates, process_game_extras, is_scan_job_running
from sharewarez.utils.igdb_api import IGDBRateLimiter
from sharewarez.utils.security import is_safe_path, get_allowed_base_directories
from sharewarez.utils.background_jobs import enqueue
from sharewarez.utils.scan_targets import resolve_scan_target, enumerate_scan_target, validate_scan_candidate
from sharewarez.utils.incremental_scanning import filesystem_fingerprint
from sharewarez.utils.metadata_provenance import merge_provider_metadata


@dataclass(frozen=True)
class MetadataRefreshResult:
    """Outcome of remote metadata refresh and optional local enrichment."""

    game_name: str
    filesystem_skipped: bool = False
    filesystem_message: str | None = None


def _scan_enabled_supplemental_content(game_name, full_disk_path, library_uuid,
                                       enable_game_updates, update_folder_name,
                                       enable_game_extras, extras_folder_name):
    """Scan enabled update/extra directories for both new and existing games."""
    if enable_game_updates:
        updates_folder = os.path.join(full_disk_path, update_folder_name)
        if os.path.isdir(updates_folder):
            print(f"Updates folder found for game: {game_name}")
            process_game_updates(game_name, full_disk_path, updates_folder, library_uuid, update_folder_name)
        else:
            print(f"No updates folder found for game: {game_name}")
    else:
        print(f"Updates scanning disabled, skipping for game: {game_name}")

    if enable_game_extras:
        extras_folder = os.path.join(full_disk_path, extras_folder_name)
        if os.path.isdir(extras_folder):
            print(f"Extras folder found for game: {game_name}")
            process_game_extras(game_name, full_disk_path, extras_folder, library_uuid, extras_folder_name)
        else:
            print(f"No extras folder found for game: {game_name}")
    else:
        print(f"Extras scanning disabled, skipping for game: {game_name}")


def refresh_game_metadata_and_updates(game_uuid):
    """Refresh IGDB, HLTB, filesystem, and supplemental metadata for one game."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
    if not game:
        raise ValueError('Game not found')

    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    update_folder_name = settings.update_folder_name if settings else 'updates'
    extras_folder_name = settings.extras_folder_name if settings else 'extras'
    enable_game_updates = bool(settings and settings.enable_game_updates)
    enable_game_extras = bool(settings and settings.enable_game_extras)

    if not game.igdb_id or game.igdb_id >= 2000000420:
        raise ValueError('This game does not have a refreshable IGDB ID')

    response = fetch_game_by_igdb_id(game.igdb_id)
    if not response:
        raise RuntimeError('IGDB returned no metadata for this game')
    metadata = response[0]

    scalar_fields = (
        'name', 'summary', 'storyline', 'url', 'slug',
        'aggregated_rating', 'aggregated_rating_count',
        'rating', 'rating_count', 'total_rating', 'total_rating_count',
    )
    provider_values = {
        field: metadata.get(field) for field in scalar_fields if field in metadata
    }

    if metadata.get('first_release_date'):
        provider_values['first_release_date'] = datetime.fromtimestamp(
            metadata['first_release_date'], timezone.utc
        )
    if metadata.get('category') in category_mapping:
        provider_values['category'] = category_mapping[metadata['category']]
    if metadata.get('status') in status_mapping:
        provider_values['status'] = status_mapping[metadata['status']]

    if 'videos' in metadata:
        provider_values['video_urls'] = ','.join(
            f"https://www.youtube.com/embed/{video['video_id']}"
            for video in metadata.get('videos', [])
            if video.get('video_id')
        )

    merge_provider_metadata(game, provider_values)

    from sharewarez.utils.game_relationships import sync_game_relationships
    sync_game_relationships(game, metadata)

    relationship_fields = (
        ('genres', Genre),
        ('themes', Theme),
        ('game_modes', GameMode),
        ('platforms', Platform),
        ('player_perspectives', PlayerPerspective),
    )
    for field, model in relationship_fields:
        if field in metadata:
            values = [
                get_or_create_entity(model, name=item['name'])
                for item in metadata.get(field, [])
                if isinstance(item, dict) and item.get('name')
            ]
            setattr(game, field, values)

    involved_companies = metadata.get('involved_companies') or []
    if involved_companies:
        # Older edit forms could accidentally save SQLAlchemy's display value
        # (for example ``<Developer 6>``) as the company name. Clear only
        # those known placeholders before resolving the real IGDB company.
        if game.developer and re.fullmatch(r'<Developer \d+>', game.developer.name or ''):
            game.developer = None
        if game.publisher and re.fullmatch(r'<Publisher \d+>', game.publisher.name or ''):
            game.publisher = None
        enumerate_companies(game, game.igdb_id, involved_companies)

    filesystem_message = None
    path_available = bool(game.full_disk_path and os.path.isdir(game.full_disk_path))
    if path_available:
        allowed_bases = get_allowed_base_directories(current_app)
        path_is_safe, error_message = is_safe_path(game.full_disk_path, allowed_bases)
        if not path_is_safe:
            path_available = False
            filesystem_message = f'Filesystem enrichment skipped: {error_message}'
    else:
        filesystem_message = (
            'Filesystem enrichment skipped because the game path is unavailable: '
            f"{game.full_disk_path or 'not configured'}"
        )

    if path_available:
        game.nfo_content = read_first_nfo_content(game.full_disk_path)
        game.size = get_folder_size_in_bytes_updates(game.full_disk_path)
    game.last_updated = datetime.now(timezone.utc)
    db.session.commit()

    if path_available:
        _scan_enabled_supplemental_content(
            game.name, game.full_disk_path, game.library_uuid,
            enable_game_updates, update_folder_name,
            enable_game_extras, extras_folder_name
        )
    elif filesystem_message:
        current_app.logger.info('%s (%s)', filesystem_message, game.uuid)

    if settings and settings.enable_hltb_integration:
        from sharewarez.utils.hltb import update_game_hltb_sync
        update_game_hltb_sync(game.uuid, game.name)

    return MetadataRefreshResult(
        game_name=game.name,
        filesystem_skipped=not path_available,
        filesystem_message=filesystem_message,
    )


# Compatibility entry point for integrations and focused scan tests.
from sharewarez.utils.scan_execution import scan_and_add_games


def handle_auto_scan(auto_form):
    print("handle_auto_scan: function running.")
    print(f"Auto-scan form data: {auto_form.data}")
    library_uuid = auto_form.library_uuid.data
    if auto_form.validate_on_submit():
        remove_missing = auto_form.remove_missing.data
        download_missing_images = auto_form.download_missing_images.data
        force_updates_extras_scan = auto_form.force_updates_extras_scan.data
        fetch_hltb = auto_form.fetch_hltb.data
        force_hltb_refetch = auto_form.force_hltb_refetch.data
        
        running_job = db.session.execute(select(ScanJob).filter_by(status='Running')).scalars().first()
        if running_job:
            print("A scan is already in progress. Please wait until the current scan completes.")
            flash('A scan is already in progress. Please wait until the current scan completes.', 'error')
            session['active_tab'] = 'auto'
            return redirect(url_for('main.admin_scan_management', library_uuid=library_uuid, active_tab='auto'))

    
        library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
        if not library:
            print("Selected library does not exist. Please select a valid library.")
            flash('Selected library does not exist. Please select a valid library.', 'error')
            return redirect(url_for('main.admin_scan_management', active_tab='auto'))

        folder_path = auto_form.folder_path.data
        scan_mode = auto_form.scan_mode.data        
        print(f"Auto-scan form submitted. Library: {library.name}, Folder: {folder_path}, Scan mode: {scan_mode}, Download missing images: {download_missing_images}")
        
        try:
            extensions = db.session.execute(select(AllowedFileType.value)).scalars().all()
            full_path = resolve_scan_target(folder_path, scan_mode, extensions=extensions).path
        except (ValueError, OSError) as exc:
            flash(f'Cannot scan this target: {exc}', 'error')
            return redirect(url_for('main.admin_scan_management', active_tab='auto'))

        background_job = enqueue(
            'library.scan',
            {
                'force_scan': True,
                'folder_path': full_path,
                'scan_mode': scan_mode,
                'library_uuid': library_uuid,
                'remove_missing': remove_missing,
                'download_missing_images': download_missing_images,
                'force_updates_extras_scan': force_updates_extras_scan,
                'fetch_hltb': fetch_hltb,
                'force_hltb_refetch': force_hltb_refetch,
            },
            queue='default',
            max_attempts=3,
        )
        
        flash(
            f"Auto-scan queued for {library.name} (job {background_job.id}).",
            'info',
        )
        session['active_tab'] = 'auto'
    else:
        flash(f"Auto-scan form validation failed: {auto_form.errors}")
        print(f"Auto-scan form validation failed: {auto_form.errors}")
    return redirect(url_for('main.admin_scan_management', library_uuid=library_uuid, active_tab='auto'))



def handle_manual_scan(manual_form):
    from sharewarez.utils.manual_scan import clear_manual_selection, start_manual_selection
    clear_manual_selection()
    session['active_tab'] = 'manual'
    library_uuid = manual_form.library_uuid.data
    try:
        if manual_form.validate_on_submit():
            # check job status
            running_job = db.session.execute(select(ScanJob).filter_by(status='Running')).scalars().first()
            if running_job:
                flash('A scan is already in progress. Please wait until the current scan completes.', 'error')
                session['active_tab'] = 'manual'
                return redirect(url_for('main.admin_scan_management', active_tab='manual'))
            
            folder_path = (manual_form.folder_path.data or '').strip()
            scan_mode = manual_form.scan_mode.data or 'folders'
            force_updates_extras_scan = manual_form.force_updates_extras_scan.data
            fetch_hltb = manual_form.fetch_hltb.data
            force_hltb_refetch = manual_form.force_hltb_refetch.data
            
            if not library_uuid:
                flash('Please select a library.', 'error')
                return redirect(url_for('main.admin_scan_management', active_tab='manual'))
            
            # Store library_uuid in session for use in identify page
            session['selected_library_uuid'] = library_uuid
            print(f"Manual scan: Selected library UUID: {library_uuid}")

            try:
                extensions = db.session.execute(select(AllowedFileType.value)).scalars().all()
                if scan_mode == 'files' and not extensions:
                    raise ValueError('No allowed file types configured. Enable them in Scan Manager → File types.')
                target = resolve_scan_target(folder_path, scan_mode, extensions=extensions)
                full_path = target.path
            except (ValueError, OSError) as exc:
                flash(f'Cannot scan this target: {exc}', 'error')
                return redirect(url_for('main.admin_scan_management', active_tab='manual'))

            if os.path.exists(full_path) and os.access(full_path, os.R_OK):
                print("Folder or file exists and can be accessed.")
                insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()
                games_with_paths, complete = enumerate_scan_target(
                    target, extensions, insensitive_patterns, sensitive_patterns,
                )
                if not complete:
                    flash('Some scan entries could not be read or were outside the selected target and were skipped.', 'warning')
                start_manual_selection(library_uuid, target, {
                    'force_updates_extras_scan': bool(force_updates_extras_scan),
                    'fetch_hltb': bool(fetch_hltb), 'force_hltb_refetch': bool(force_hltb_refetch),
                })
                flash('Manual scan processed for target: ' + full_path, 'info')
                
            else:
                flash("Folder or file does not exist or cannot be accessed.", "error")
        else:
            flash('Manual scan form validation failed.', 'error')
    except Exception as exc:
        current_app.logger.exception("Unexpected error in handle_manual_scan: %s", exc)
        flash(f'Manual scan failed: {str(exc)}', 'error')
        
    return redirect(url_for('main.admin_scan_management', library_uuid=library_uuid, active_tab='manual'))
