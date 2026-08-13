#/sharewarez/utilities.py
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


def scan_and_add_games(folder_path, scan_mode='folders', library_uuid=None, remove_missing=False, existing_job=None, download_missing_images=False, force_updates_extras_scan=False, fetch_hltb=False, force_hltb_refetch=False):
    # Only check for running jobs if we're not restarting an existing job
    if not existing_job and is_scan_job_running():
        print("A scan is already in progress. Please wait for it to complete.")
        return
        
    # Cache settings once at the start of scan
    settings_obj = db.session.execute(select(GlobalSettings)).scalars().first()
    update_folder_name = settings_obj.update_folder_name if settings_obj else 'updates'
    extras_folder_name = settings_obj.extras_folder_name if settings_obj else 'extras'
    enable_game_updates = settings_obj.enable_game_updates if settings_obj else False
    enable_game_extras = settings_obj.enable_game_extras if settings_obj else False
    scan_thread_count = settings_obj.scan_thread_count if settings_obj else 1

    # Extract local metadata settings into a plain dict (thread-safe)
    # We can't pass SQLAlchemy objects across threads, so extract values now
    settings_dict = {
        'use_local_metadata': settings_obj.use_local_metadata if settings_obj else False,
        'write_local_metadata': settings_obj.write_local_metadata if settings_obj else False,
        'use_local_images': settings_obj.use_local_images if settings_obj else False,
        'local_metadata_filename': settings_obj.local_metadata_filename if settings_obj else 'sharewarez.json'
    }

    # Log local metadata settings once at scan start
    if settings_obj:
        print(f"📋 [LOCAL METADATA] Settings: use_local_metadata={settings_dict['use_local_metadata']}, write_local_metadata={settings_dict['write_local_metadata']}, use_local_images={settings_dict['use_local_images']}")
    
    # Initialize IGDB rate limiter for scanning operations
    igdb_rate_limiter = IGDBRateLimiter()
    
    # Bulk prefetch existing games and unmatched folders for performance
    print("Prefetching existing games and unmatched folders...")
    existing_game_paths = set(
        db.session.execute(
            select(Game.full_disk_path).filter_by(library_uuid=library_uuid)
        ).scalars().all()
    )
    existing_unmatched_paths = set(
        db.session.execute(
            select(UnmatchedFolder.folder_path).filter_by(library_uuid=library_uuid)
        ).scalars().all()
    )
    print(f"Prefetched {len(existing_game_paths)} existing games and {len(existing_unmatched_paths)} unmatched folders")
    
    # First, find the library and its platform
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if not library:
        print(f"Library with UUID {library_uuid} not found.")
        return

    # Get allowed file types from database
    allowed_extensions = [ext.value.lower() for ext in db.session.execute(select(AllowedFileType)).scalars().all()]
    if not allowed_extensions:
        print("No allowed file types found in database. Please configure them in the admin panel.")
        return

    print(f"Starting auto scan for games in folder: {folder_path} with scan mode: {scan_mode} and library UUID: {library_uuid} for platform: {library.platform.name}")
    
    # Use existing job or create new one
    if existing_job:
        # Re-query the job to ensure it's bound to the current session
        scan_job_entry = db.session.get(ScanJob, existing_job.id)
        print(f"Using existing scan job: {scan_job_entry.id}")
    else:
        # Create initial scan job
        scan_job_entry = ScanJob(
            folders={folder_path: True},
            content_type='Games',
            status='Running',
            is_enabled=True,
            last_run=datetime.now(),
            library_uuid=library_uuid,
            error_message='',
            total_folders=0,
            folders_success=0,
            folders_failed=0,
            removed_count=0,
            scan_folder=folder_path,
            setting_remove=remove_missing,
            setting_filefolder=(scan_mode == 'files'),
            setting_download_missing_images=download_missing_images,
            setting_force_updates_extras=force_updates_extras_scan
        )
        
        db.session.add(scan_job_entry)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            print(f"Database error when adding ScanJob: {str(e)}")
            return  # cannot proceed without ScanJob

    # Check access perm
    if not os.path.exists(folder_path) or not os.access(folder_path, os.R_OK):
        error_message = f"Cannot access folder at path {folder_path}. Check permissions."
        print(error_message)
        scan_job_entry.status = 'Failed'
        scan_job_entry.error_message = error_message
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            print(f"Database error when updating ScanJob with error: {str(e)}")
        return

    # Load patterns before they are used
    insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()

    try:
        # Use database-stored allowed extensions
        if scan_mode == 'folders':
            game_names_with_paths = get_game_names_from_folder(folder_path, insensitive_patterns, sensitive_patterns)
        elif scan_mode == 'files':
            game_names_with_paths = get_game_names_from_files(folder_path, allowed_extensions, insensitive_patterns, sensitive_patterns)

        scan_job_entry.total_folders = len(game_names_with_paths)
        db.session.commit()
        if not game_names_with_paths:
            print(f"No games found in folder: {folder_path}")
            scan_job_entry.status = 'Completed'
            scan_job_entry.error_message = "No games found."
            db.session.commit()
            return
    except Exception as e:
        scan_job_entry.status = 'Failed'
        scan_job_entry.error_message = str(e)
        db.session.commit()
        print(f"Error during pattern loading or game name extraction: {str(e)}")
        return

    def process_single_game(game_info, scan_job_id, library_uuid, update_folder_name, extras_folder_name, enable_game_updates, enable_game_extras, existing_game_paths, existing_unmatched_paths, igdb_rate_limiter, app, force_updates_extras_scan=False, fetch_hltb=False, force_hltb_refetch=False, settings=None):
        """Process a single game with rate limiting and thread-safe database operations."""
        game_name = game_info['name']
        full_disk_path = game_info['full_path']
        result = {'game_name': game_name, 'success': False, 'error': None}
        
        # Existing games still need their enabled supplemental content checked.
        # This is intentionally independent of the legacy per-scan force flag:
        # enabling update/extras scanning globally is the source of truth.
        if existing_game_paths and full_disk_path in existing_game_paths:
            print(f"Game already exists (cached): {game_name} at {full_disk_path}")
            should_process_existing = enable_game_updates or enable_game_extras or force_hltb_refetch
            if enable_game_updates or enable_game_extras:
                print(f"Enabled supplemental scan, checking existing game: {game_name}")
            if force_hltb_refetch:
                print(f"Force HLTB refetch enabled, will update HLTB data for existing game: {game_name}")

            if not should_process_existing:
                return {'game_name': game_name, 'success': True, 'already_exists': True}

            game_already_exists = True
        else:
            game_already_exists = False
        
        if existing_unmatched_paths and full_disk_path in existing_unmatched_paths:
            print(f"Folder already logged as unmatched (cached): {full_disk_path}")
            return {'game_name': game_name, 'success': False, 'already_unmatched': True}
        
        # Ensure we have a Flask app context for database operations
        with app.app_context():
            try:
                # Use rate limiter for IGDB API calls
                igdb_rate_limiter.acquire()
                try:
                    # Existing games skip identification and go directly to enabled supplemental scans.
                    if game_already_exists:
                        success = True
                        print(f"Skipping identification for existing game: {game_name}")
                    else:
                        success = process_game_with_fallback(game_name, full_disk_path, scan_job_id, library_uuid, fetch_hltb=fetch_hltb, settings=settings)
                    
                    result['success'] = success
                    
                    if success:
                        _scan_enabled_supplemental_content(
                            game_name, full_disk_path, library_uuid,
                            enable_game_updates, update_folder_name,
                            enable_game_extras, extras_folder_name
                        )

                        # Fetch HLTB data for existing games if force_hltb_refetch is enabled
                        if game_already_exists and force_hltb_refetch:
                            try:
                                from sharewarez.models import GlobalSettings
                                settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
                                if settings and settings.enable_hltb_integration:
                                    from sharewarez.utils.hltb import update_game_hltb_sync
                                    # Get the game UUID from database
                                    from sharewarez.models import Game
                                    game_obj = db.session.execute(
                                        select(Game).where(Game.full_disk_path == full_disk_path)
                                    ).scalars().first()
                                    if game_obj:
                                        print(f"Refetching HLTB data for existing game '{game_name}'...")
                                        update_game_hltb_sync(game_obj.uuid, game_obj.name)
                                    else:
                                        print(f"Could not find game in database to refetch HLTB: {game_name}")
                            except Exception as e:
                                print(f"Failed to refetch HLTB data for '{game_name}': {e}")
                                # Don't fail the scan if HLTB fetch fails
                    else:
                        result['unmatched'] = True
                        print(f"[PROCESS INFO] Game '{game_name}' could not be matched to IGDB database or was already unmatched.")
                        print(f"[PROCESS INFO] Game path: {full_disk_path}")
                        print("[PROCESS INFO] This is informational, not an error")
                        
                finally:
                    igdb_rate_limiter.release()
                    
            except Exception as e:
                result['error'] = str(e)
                print(f"[PROCESS EXCEPTION] Exception in process_single_game for '{game_name}': {str(e)}")
                print(f"[PROCESS EXCEPTION] Game path: {full_disk_path}")
                print(f"[PROCESS EXCEPTION] Full exception: {repr(e)}")
                import traceback
                print(f"[PROCESS EXCEPTION] Traceback: {traceback.format_exc()}")
                
        return result
    
    # Process games either sequentially or in parallel based on thread count
    if scan_thread_count > 1:
        # Multithreaded processing
        print(f"Using multithreaded scanning with {scan_thread_count} threads")
        with ThreadPoolExecutor(max_workers=scan_thread_count) as executor:
            # Submit all game processing tasks
            future_to_game = {
                executor.submit(process_single_game, game_info, scan_job_entry.id, library_uuid,
                              update_folder_name, extras_folder_name, enable_game_updates, enable_game_extras,
                              existing_game_paths, existing_unmatched_paths, igdb_rate_limiter, current_app._get_current_object(),
                              force_updates_extras_scan, fetch_hltb, force_hltb_refetch, settings_dict): game_info
                for game_info in game_names_with_paths
            }
            
            # Process completed futures
            for future in as_completed(future_to_game):
                # Check for shutdown request
                from sharewarez.utils.shutdown import should_continue_processing
                if not should_continue_processing():
                    print("🛑 Shutdown requested during scan, cancelling remaining tasks...")
                    # Cancel remaining tasks
                    for f in future_to_game:
                        f.cancel()
                    scan_job_entry.status = 'Cancelled'
                    scan_job_entry.error_message = 'Scan cancelled due to application shutdown'
                    db.session.commit()
                    return
                
                # Check if the job is still enabled
                db.session.refresh(scan_job_entry)
                if not scan_job_entry.is_enabled:
                    # Cancel remaining tasks
                    for f in future_to_game:
                        f.cancel()
                    scan_job_entry.status = 'Cancelled'
                    scan_job_entry.error_message = 'Scan cancelled by user'
                    scan_job_entry.current_processing = None
                    db.session.commit()
                    return
                
                game_info = future_to_game[future]
                try:
                    result = future.result()
                    if result['success']:
                        scan_job_entry.folders_success += 1
                    elif result.get('unmatched'):
                        # Unmatched games are not errors, just increment failed count for tracking
                        scan_job_entry.folders_failed += 1
                        print(f"[SCAN INFO] Game '{result['game_name']}' was unmatched (not an error)")
                    else:
                        scan_job_entry.folders_failed += 1
                        
                    # Only add actual errors to error_message, not unmatched games
                    if result.get('error') and not result.get('unmatched'):
                        error_line = f"Failed to process '{result['game_name']}': {result['error']}"
                        scan_job_entry.error_message = (scan_job_entry.error_message or "") + f"{error_line}\n"
                        print(f"[SCAN ERROR] {error_line}")
                        print(f"[SCAN ERROR] Game path: {future_to_game[future]['full_path']}")
                        print(f"[SCAN ERROR] Full result: {result}")
                        
                except Exception as e:
                    scan_job_entry.folders_failed += 1
                    error_line = f"Exception processing '{game_info['name']}': {str(e)}"
                    scan_job_entry.error_message = (scan_job_entry.error_message or "") + f"{error_line}\n"
                    print(f"[SCAN EXCEPTION] {error_line}")
                    print(f"[SCAN EXCEPTION] Game path: {game_info.get('full_path', 'unknown')}")
                    print(f"[SCAN EXCEPTION] Full exception: {repr(e)}")
                    import traceback
                    print(f"[SCAN EXCEPTION] Traceback: {traceback.format_exc()}")
                    
                db.session.commit()
    else:
        # Sequential processing (original behavior)
        print("Using single-threaded sequential scanning")
        
        # Progress tracking variables
        processed_count = 0
        already_exist_count = 0
        new_games_count = 0
        already_unmatched_count = 0
        scan_start_time = datetime.now()
        
        for game_info in game_names_with_paths:
            db.session.refresh(scan_job_entry)  # Check if the job is still enabled
            if not scan_job_entry.is_enabled:
                scan_job_entry.status = 'Cancelled'
                scan_job_entry.error_message = 'Scan cancelled by user'
                scan_job_entry.current_processing = None
                db.session.commit()
                return  # Stop processing if cancelled
            
            game_name = game_info['name']
            full_disk_path = game_info['full_path']
            processed_count += 1
            
            # Fast path - check cached sets BEFORE database queries
            if existing_game_paths and full_disk_path in existing_game_paths:
                print(f"Game already exists (cached): {game_name} at {full_disk_path}")
                already_exist_count += 1
                scan_job_entry.folders_success += 1
                try:
                    _scan_enabled_supplemental_content(
                        game_name, full_disk_path, library_uuid,
                        enable_game_updates, update_folder_name,
                        enable_game_extras, extras_folder_name
                    )
                except Exception as e:
                    scan_job_entry.folders_failed += 1
                    scan_job_entry.folders_success -= 1
                    scan_job_entry.status = 'Failed'
                    error_line = f"Failed supplemental scan for '{game_name}': {str(e)}"
                    scan_job_entry.error_message = (scan_job_entry.error_message or "") + f"{error_line}\n"
                    print(f"[SCAN EXCEPTION] {error_line}")
            elif existing_unmatched_paths and full_disk_path in existing_unmatched_paths:
                print(f"Folder already logged as unmatched (cached): {full_disk_path}")
                already_unmatched_count += 1
                scan_job_entry.folders_failed += 1
            else:
                try:
                    success = process_game_with_fallback(game_name, full_disk_path, scan_job_entry.id, library_uuid, existing_game_paths, existing_unmatched_paths, fetch_hltb=fetch_hltb, settings=settings_dict)
                    if success:
                        new_games_count += 1
                        scan_job_entry.folders_success += 1
                        _scan_enabled_supplemental_content(
                            game_name, full_disk_path, library_uuid,
                            enable_game_updates, update_folder_name,
                            enable_game_extras, extras_folder_name
                        )
                    else:
                        scan_job_entry.folders_failed += 1
                        print(f"[SCAN INFO] Game '{game_name}' could not be matched to IGDB database or was already unmatched.")
                        print(f"[SCAN INFO] Game path: {full_disk_path}")
                        print("[SCAN INFO] This is informational, not an error")

                except Exception as e:
                    print(f"[SCAN EXCEPTION] Exception processing game '{game_name}': {str(e)}")
                    print(f"[SCAN EXCEPTION] Game path: {full_disk_path}")
                    print(f"[SCAN EXCEPTION] Full exception: {repr(e)}")
                    import traceback
                    print(f"[SCAN EXCEPTION] Traceback: {traceback.format_exc()}")
                    scan_job_entry.folders_failed += 1
                    scan_job_entry.status = 'Failed'
                    error_line = f"Exception processing '{game_name}': {str(e)}"
                    scan_job_entry.error_message = (scan_job_entry.error_message or "") + f"{error_line}\n"
            
            # Commit after each game and update progress
            scan_job_entry.current_processing = f"Processing: {game_name} ({processed_count}/{len(game_names_with_paths)})"
            scan_job_entry.last_progress_update = datetime.now()
            
            db.session.commit()
            
            # Log detailed progress every 10 games
            if processed_count % 10 == 0 or processed_count == len(game_names_with_paths):
                print(f"Committed: {processed_count}/{len(game_names_with_paths)} games processed")
                
                elapsed_time = (datetime.now() - scan_start_time).total_seconds()
                games_per_second = processed_count / elapsed_time if elapsed_time > 0 else 0
                estimated_remaining = (len(game_names_with_paths) - processed_count) / games_per_second if games_per_second > 0 else 0
                
                print(f"Progress: {processed_count}/{len(game_names_with_paths)} games processed")
                print(f"Speed: {games_per_second:.1f} games/sec")
                if estimated_remaining > 0:
                    print(f"Estimated time remaining: {estimated_remaining:.0f} seconds")
                print(f"Skipped (already exist): {already_exist_count}")
                print(f"New games found: {new_games_count}")
                print(f"Already unmatched: {already_unmatched_count}")

    if scan_job_entry.status != 'Failed':
        scan_job_entry.status = 'Completed'
    
    # If remove_missing is enabled, check for games that no longer exist
    if remove_missing:
        print("Checking for missing games...")
        games_in_library = db.session.execute(select(Game).filter_by(library_uuid=library_uuid)).scalars().all()
        for game in games_in_library:
            if not os.path.exists(game.full_disk_path):
                print(f"Game no longer found at path: {game.full_disk_path}")
                try:
                    remove_from_lib(game.uuid)
                    scan_job_entry.removed_count += 1
                    print(f"Removed game {game.name} as it no longer exists at {game.full_disk_path}")
                except Exception as e:
                    print(f"Error removing game {game.name}: {e}")

    # If download_missing_images is enabled, check for and queue missing images
    if download_missing_images:
        print("🔍 Download missing images option enabled - checking for missing images...")
        try:
            from sharewarez.utils.game_core import process_missing_images_for_scan
            result = process_missing_images_for_scan(library_uuid, current_app._get_current_object())
            
            if result.get('success'):
                message = f"Missing images scan: {result['message']}"
                print(message)
                
                # Add to scan job status for user feedback
                if scan_job_entry.error_message:
                    scan_job_entry.error_message += f" | {message}"
                else:
                    scan_job_entry.error_message = message
                    
            else:
                error_message = f"Missing images scan failed: {result.get('error', 'Unknown error')}"
                print(error_message)
                scan_job_entry.error_message += f" | {error_message}"
                
        except Exception as e:
            error_message = f"Error during missing images processing: {str(e)}"
            print(error_message)
            scan_job_entry.error_message += f" | {error_message}"

    try:
        # Truncate error message if it's too long
        if scan_job_entry.error_message and len(scan_job_entry.error_message) > 500:
            scan_job_entry.error_message = scan_job_entry.error_message[:497] + "..."
        
        db.session.commit()
        print(f"Scan completed for folder: {folder_path} with ScanJob ID: {scan_job_entry.id}")
    except SQLAlchemyError as e:
        print(f"Database error when finalizing ScanJob: {str(e)}")
        
        


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
            return redirect(url_for('main.scan_management', library_uuid=library_uuid, active_tab='auto'))

    
        library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
        if not library:
            print("Selected library does not exist. Please select a valid library.")
            flash('Selected library does not exist. Please select a valid library.', 'error')
            return redirect(url_for('main.scan_management', active_tab='auto'))

        folder_path = auto_form.folder_path.data
        scan_mode = auto_form.scan_mode.data        
        print(f"Auto-scan form submitted. Library: {library.name}, Folder: {folder_path}, Scan mode: {scan_mode}, Download missing images: {download_missing_images}")
        
        # Validate folder path security
        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'error')
            return redirect(url_for('main.scan_management', active_tab='auto'))
        
        # Prepend the base path
        base_dir = current_app.config.get('BASE_FOLDER_WINDOWS') if os.name == 'nt' else current_app.config.get('BASE_FOLDER_POSIX')
        full_path = os.path.join(base_dir, folder_path)
        
        # Security validation: ensure the constructed path is within allowed directories
        is_safe, error_message = is_safe_path(full_path, allowed_bases)
        if not is_safe:
            print(f"Security error: Auto-scan path validation failed for {full_path}: {error_message}")
            flash(f"Access denied: {error_message}", 'error')
            return redirect(url_for('main.scan_management', active_tab='auto'))
        
        if not os.path.exists(full_path) or not os.access(full_path, os.R_OK):
            flash(f"Cannot access folder: {full_path}. Please check the path and permissions.", 'error')
            print(f"Cannot access folder: {full_path}. Please check the path and permissions.", 'error')
            session['active_tab'] = 'auto'
            return redirect(url_for('library.library'))

        background_job = enqueue(
            'library.scan',
            {
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
    return redirect(url_for('main.scan_management', library_uuid=library_uuid, active_tab='auto'))



def handle_manual_scan(manual_form):
    session['active_tab'] = 'manual'
    library_uuid = manual_form.library_uuid.data
    if manual_form.validate_on_submit():
        # check job status
        running_job = db.session.execute(select(ScanJob).filter_by(status='Running')).scalars().first()
        if running_job:
            flash('A scan is already in progress. Please wait until the current scan completes.', 'error')
            session['active_tab'] = 'manual'
            return redirect(url_for('main.scan_management', active_tab='manual'))
        
        folder_path = manual_form.folder_path.data
        scan_mode = manual_form.scan_mode.data
        force_updates_extras_scan = manual_form.force_updates_extras_scan.data
        fetch_hltb = manual_form.fetch_hltb.data
        force_hltb_refetch = manual_form.force_hltb_refetch.data
        
        if not library_uuid:
            flash('Please select a library.', 'error')
            return redirect(url_for('main.scan_management', active_tab='manual'))
        
        # Store library_uuid in session for use in identify page
        session['selected_library_uuid'] = library_uuid
        print(f"Manual scan: Selected library UUID: {library_uuid}")

        # Validate folder path security
        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'error')
            return redirect(url_for('main.scan_management', active_tab='manual'))

        base_dir = current_app.config.get('BASE_FOLDER_WINDOWS') if os.name == 'nt' else current_app.config.get('BASE_FOLDER_POSIX')
        full_path = os.path.join(base_dir, folder_path)
        print(f"Manual scan form submitted. Full path: {full_path}, Library UUID: {library_uuid}")
        
        # Security validation: ensure the constructed path is within allowed directories
        is_safe, error_message = is_safe_path(full_path, allowed_bases)
        if not is_safe:
            print(f"Security error: Manual scan path validation failed for {full_path}: {error_message}")
            flash(f"Access denied: {error_message}", 'error')
            return redirect(url_for('main.scan_management', active_tab='manual'))

        # Check write permissions if local metadata writing is enabled
        from sharewarez.utils.local_metadata import check_library_write_permissions
        settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()

        if settings and settings.write_local_metadata:
            print(f"🔍 [PERMISSIONS] Checking write permissions for library path: {full_path}")
            all_ok, failed_paths = check_library_write_permissions(full_path)

            if not all_ok:
                print(f"🚫 [PERMISSIONS] Write permission check failed for {len(failed_paths)} path(s)")
                # Store permission errors in session to show in modal
                session['permission_check_failed'] = True
                session['permission_errors'] = failed_paths
                session['permission_check_path'] = full_path
                flash('Write permission check failed. Please review the permission errors.', 'error')
                return redirect(url_for('main.scan_management', active_tab='manual', show_permissions_modal='true'))

        if os.path.exists(full_path) and os.access(full_path, os.R_OK):
            print("Folder exists and can be accessed.")
            insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()
            if scan_mode == 'folders':
                games_with_paths = get_game_names_from_folder(full_path, insensitive_patterns, sensitive_patterns)
            else:  # files mode
                # Load allowed file types from database
                allowed_file_types = db.session.execute(select(AllowedFileType)).scalars().all()
                supported_extensions = [file_type.value for file_type in allowed_file_types]
                if not supported_extensions:
                    flash("No allowed file types defined in the database.", "error")
                    return redirect(url_for('main.scan_management', active_tab='manual'))
                
                games_with_paths = get_game_names_from_files(full_path, supported_extensions, insensitive_patterns, sensitive_patterns)
            session['game_paths'] = {game['name']: game['full_path'] for game in games_with_paths}
            session['force_updates_extras_scan'] = force_updates_extras_scan
            session['fetch_hltb'] = fetch_hltb
            session['force_hltb_refetch'] = force_hltb_refetch
            print(f"Found {len(session['game_paths'])} games in the folder.")
            flash('Manual scan processed for folder: ' + full_path, 'info')
            
        else:
            flash("Folder does not exist or cannot be accessed.", "error")
    else:
        flash('Manual scan form validation failed.', 'error')
        
    print("Game paths: ", session.get('game_paths', {}))
    return redirect(url_for('main.scan_management', library_uuid=library_uuid, active_tab='manual'))
