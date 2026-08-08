import json
import os
from datetime import date, datetime, timezone
from flask import current_app, flash, has_request_context
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import (
    Game, 
    Image, 
    Library, 
    GameUpdate, 
    GameExtra, 
    UnmatchedFolder,
    GlobalSettings,
    ScanJob
)
from sharewarez.utils.functions import read_first_nfo_content
from sharewarez.utils.igdb_api import make_igdb_api_request
from sharewarez.utils.event_logging import log_system_event


def try_add_game(game_name, full_disk_path, scan_job_id, library_uuid, check_exists=True, fetch_hltb=False, settings=None):
    from sharewarez.utils.game_core import (
        retrieve_and_save_game
    )

    # Fetch the library details using the library_uuid, if necessary
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    if not library:
        print(f"Library with UUID {library_uuid} not found.")
        return False

    if check_exists:
        existing_game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path)).scalar_one_or_none()
        if existing_game:
            print(f"Game already exists in database: {game_name} at {full_disk_path}")
            return False

    game = retrieve_and_save_game(game_name, full_disk_path, scan_job_id, library_uuid, fetch_hltb=fetch_hltb, settings=settings)
    return game is not None


def process_game_with_fallback(game_name, full_disk_path, scan_job_id, library_uuid, existing_game_paths=None, existing_unmatched_paths=None, fetch_hltb=False, settings=None):
    # Fast path - check cached sets first if provided
    if existing_game_paths and full_disk_path in existing_game_paths:
        print(f"Game already exists (fast path): {game_name} at {full_disk_path}")
        return True
    
    if existing_unmatched_paths and full_disk_path in existing_unmatched_paths:
        print(f"Folder already logged as unmatched (fast path): {full_disk_path}")
        return False
    
    # Fetch library details based on library_uuid
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    scan_job = db.session.get(ScanJob, scan_job_id)
    if not library:
        print(f"Library with UUID {library_uuid} not found.")
        return False

    # Log skipping of processing for already matched or unmatched folders (fallback for when cached sets not provided)
    if not existing_unmatched_paths:
        existing_unmatched_folder = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=full_disk_path)).scalar_one_or_none()
        if existing_unmatched_folder:
            print(f"Skipping processing for already logged unmatched folder: {full_disk_path}")
            # Update total count to maintain consistency even when skipping
            scan_job.folders_failed += 1
            return False

    # Check if the game already exists in the database (fallback for when cached sets not provided)
    if not existing_game_paths:
        existing_game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)).scalar_one_or_none()
        if existing_game:
            print(f"Game already exists in database: {game_name} at {full_disk_path}")
            # Don't increment success counter for existing games to avoid inflated counts during rescans
            return True 

    print(f'Game does not exist in database: {game_name} at {full_disk_path}')
    # Try to add the game, now using library_uuid
    if not try_add_game(game_name, full_disk_path, scan_job_id, library_uuid=library_uuid, check_exists=False, fetch_hltb=fetch_hltb, settings=settings):
        # Attempt fallback game name processing
        parts = game_name.split()
        for i in range(len(parts) - 1, 0, -1):
            fallback_name = ' '.join(parts[:i])
            if try_add_game(fallback_name, full_disk_path, scan_job_id, library_uuid=library_uuid, check_exists=False, fetch_hltb=fetch_hltb, settings=settings):
                print(f"[GAME MATCH] Success with fallback name: '{fallback_name}'")
                return True
    else:
        return True

    # If the game does not match, log it as unmatched
    matched_status = 'Unmatched'
    log_unmatched_folder(scan_job_id, full_disk_path, matched_status, library_uuid)
    return False



def log_unmatched_folder(scan_job_id, folder_path, matched_status, library_uuid=None):
    existing_unmatched_folder = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=folder_path)).scalar_one_or_none()

    if existing_unmatched_folder is None:
        unmatched_folder = UnmatchedFolder(
            folder_path=folder_path,
            failed_time=datetime.now(timezone.utc),
            content_type='Games',
            library_uuid=library_uuid,
            status=matched_status
        )
        try:
            db.session.add(unmatched_folder)
            db.session.commit()
            print(f"[UNMATCHED] Logged unmatched folder: {folder_path}")
            print(f"[UNMATCHED] Status: {matched_status}")
            print(f"[UNMATCHED] Library UUID: {library_uuid}")
            print(f"[UNMATCHED] Scan Job ID: {scan_job_id}")
        except IntegrityError:
            log_system_event(f"Failed to log unmatched folder: {folder_path}", event_type='scan', event_level='warning')
            db.session.rollback()
            print(f"[UNMATCHED ERROR] Failed to log unmatched folder due to a database error: {folder_path}")
    else:
        print(f"[UNMATCHED SKIPPED] Unmatched folder already logged for: {folder_path}. Status: {existing_unmatched_folder.status}")
        


def process_game_updates(game_name, full_disk_path, updates_folder, library_uuid, update_folder_name=None):
    settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
    # Use passed parameter or fallback to database query
    if update_folder_name is None:
        if not settings or not settings.update_folder_name:
            print("No update folder configuration found in database")
            return
        update_folder_name = settings.update_folder_name
    metadata_filename = (settings.local_metadata_filename if settings else None) or 'sharewarez.json'

    print(f"Processing updates for game: {game_name}")
    print(f"Full disk path: {full_disk_path}")
    print(f"Updates folder: {updates_folder}")
    print(f"Library UUID: {library_uuid}")

    game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)).scalar_one_or_none()
    if not game:
        print(f"Game not found in database: {game_name}")
        return

    print(f"Game found in database: {game.name} (UUID: {game.uuid})")

    update_items = []
    for name in os.listdir(updates_folder):
        path = os.path.join(updates_folder, name)
        if name.lower().endswith(('.nfo', '.sfv', '.json')):
            continue
        if os.path.isdir(path) or os.path.isfile(path):
            update_items.append(name)
    print(f"Update items found: {update_items}")

    seen_paths = set()
    for update_item in update_items:
        update_path = os.path.join(updates_folder, update_item)
        seen_paths.add(update_path)
        print(f"Processing update: {update_item}")

        # Always store the folder path to display the proper folder name in UI
        file_path = update_path
        print(f"Using update folder path: {file_path}")

        # Create or update GameUpdate record
        game_update = db.session.execute(select(GameUpdate).filter_by(game_uuid=game.uuid, file_path=file_path)).scalar_one_or_none()
        if not game_update:
            print(f"Creating new GameUpdate record for {file_path}")
            game_update = GameUpdate(
                game_uuid=game.uuid,
                file_path=file_path,
                nfo_content=read_first_nfo_content(update_path) if os.path.isdir(update_path) else None
            )
            db.session.add(game_update)
        else:
            print(f"Updating existing GameUpdate record for {file_path}")
            game_update.file_path = file_path
            game_update.nfo_content = read_first_nfo_content(update_path) if os.path.isdir(update_path) else None

        game_update.size = _path_size(update_path)
        if not game_update.metadata_managed:
            metadata = _read_update_metadata(update_path, metadata_filename)
            game_update.title = _clean_metadata_text(metadata.get('title'), 255) or update_item
            game_update.version = _clean_metadata_text(metadata.get('version'), 100)
            game_update.requires_version = _clean_metadata_text(metadata.get('requires_version'), 100)
            game_update.install_instructions = _clean_metadata_text(metadata.get('install_instructions'), 10000)
            game_update.changelog = _clean_metadata_text(metadata.get('changelog'), 20000)
            game_update.update_number = _optional_nonnegative_int(metadata.get('update_number'))
            game_update.release_date = _optional_iso_date(metadata.get('release_date'))
            game_update.is_cumulative = metadata.get('is_cumulative') is True

    # A rescan should reflect the library on disk rather than retaining dead links.
    for stale_update in db.session.execute(select(GameUpdate).filter_by(game_uuid=game.uuid)).scalars().all():
        if stale_update.file_path not in seen_paths:
            db.session.delete(stale_update)

    try:
        db.session.commit()
        print("Successfully committed GameUpdate records to database")
    except SQLAlchemyError as e:
        print(f"Error committing GameUpdate records to database: {str(e)}")
        db.session.rollback()

    print(f"Finished processing updates for game: {game_name}")


def _read_update_metadata(update_path, metadata_filename='sharewarez.json'):
    """Read optional metadata from an update directory or a file sidecar."""
    metadata_path = (os.path.join(update_path, metadata_filename) if os.path.isdir(update_path)
                     else f"{update_path}.{metadata_filename}")
    if not os.path.isfile(metadata_path):
        return {}
    try:
        with open(metadata_path, 'r', encoding='utf-8') as metadata_file:
            value = json.load(metadata_file)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        current_app.logger.warning("Could not read update metadata %s: %s", metadata_path, exc)
        return {}


def _path_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                continue
    return total


def _clean_metadata_text(value, maximum):
    if value is None:
        return None
    value = str(value).strip()
    return value[:maximum] or None


def _optional_nonnegative_int(value):
    try:
        result = int(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _optional_iso_date(value):
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    


def process_game_extras(game_name, full_disk_path, extras_folder, library_uuid, extras_folder_name=None):
    # Use passed parameter or fallback to database query
    if extras_folder_name is None:
        settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
        if not settings or not settings.extras_folder_name:
            print("No extras folder configuration found in database")
            return
        extras_folder_name = settings.extras_folder_name

    print(f"Processing extras for game: {game_name}")
    print(f"Full disk path: {full_disk_path}")
    print(f"Extras folder: {extras_folder}")
    print(f"Library UUID: {library_uuid}")

    game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)).scalar_one_or_none()
    if not game:
        print(f"Game not found in database: {game_name}")
        return

    print(f"Game found in database: {game.name} (UUID: {game.uuid})")
    extra_items = [f for f in os.listdir(extras_folder) if os.path.isfile(os.path.join(extras_folder, f)) or 
                  os.path.isdir(os.path.join(extras_folder, f))]
    print(f"Extra items found: {extra_items}")

    for extra_item in extra_items:
        extra_path = os.path.join(extras_folder, extra_item)
        print(f"Processing extra: {extra_item}")
        
        # Skip .nfo and .sfv files
        if extra_item.lower().endswith(('.nfo', '.sfv')):
            continue

        # Create or update GameExtra record
        game_extra = db.session.execute(select(GameExtra).filter_by(game_uuid=game.uuid, file_path=extra_path)).scalar_one_or_none()
        if not game_extra:
            print(f"Creating new GameExtra record for {extra_path}")
            game_extra = GameExtra(
                game_uuid=game.uuid,
                file_path=extra_path,
                nfo_content=read_first_nfo_content(os.path.dirname(extra_path))
            )
            db.session.add(game_extra)
        else:
            print(f"Updating existing GameExtra record for {extra_path}")
            game_extra.file_path = extra_path
            game_extra.nfo_content = read_first_nfo_content(os.path.dirname(extra_path))

    try:
        db.session.commit()
        print(f"Successfully processed extras for game: {game_name}")
    except SQLAlchemyError as e:
        print(f"Error processing extras for game: {str(e)}")
        db.session.rollback()

    print(f"Finished processing extras for game: {game_name}")


def refresh_images_in_background(game_uuid):
    from sharewarez import cache
    from sharewarez.utils.game_core import store_image_url_for_download
    from sharewarez.utils.functions import download_image as _download_image

    print(f"[IMAGE REFRESH] Starting background refresh process for game UUID: {game_uuid}")
    with current_app.app_context():
        cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 0}, timeout=300)

        try:
            game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
            if not game:
                print(f"[IMAGE REFRESH] Game with UUID {game_uuid} not found.")
                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
                return

            print(f"[IMAGE REFRESH] Found game: {game.name} (IGDB ID: {game.igdb_id})")
            if game.igdb_id is None:
                print(f"[IMAGE REFRESH] Game '{game.name}' has no IGDB ID, cannot refresh images.")
                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
                return

            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 20}, timeout=300)

            print(f"[IMAGE REFRESH] Fetching image IDs from IGDB API for IGDB ID: {game.igdb_id}")
            response_json = make_igdb_api_request(
                current_app.config['IGDB_API_ENDPOINT'],
                f"fields id, cover, screenshots; where id = {game.igdb_id}; limit 1;"
            )
            print(f"[IMAGE REFRESH] IGDB API response: {response_json}")

            if not response_json or 'error' in response_json:
                print(f"[IMAGE REFRESH] IGDB API returned error or empty response.")
                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
                return

            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 40}, timeout=300)

            # Delete existing image records and files for this game
            print(f"[IMAGE REFRESH] Deleting existing images for game UUID: {game_uuid}")
            delete_game_images(game_uuid)
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 60}, timeout=300)

            # Queue images into DB as pending so they appear in admin image queue
            cover_id = response_json[0].get('cover')
            if cover_id:
                if isinstance(cover_id, dict):
                    cover_id = cover_id.get('id')
                print(f"[IMAGE REFRESH] Queuing cover ID: {cover_id}")
                store_image_url_for_download(game.uuid, cover_id, image_type='cover')

            screenshots_data = response_json[0].get('screenshots', [])
            print(f"[IMAGE REFRESH] Queuing {len(screenshots_data)} screenshots.")
            for screenshot in screenshots_data:
                screenshot_id = screenshot.get('id') if isinstance(screenshot, dict) else screenshot
                store_image_url_for_download(game.uuid, screenshot_id, image_type='screenshot')

            # Commit so records appear in queue as pending
            db.session.commit()
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 75}, timeout=300)

            # Immediately download this game's pending images
            pending = db.session.execute(
                select(Image).filter_by(game_uuid=game_uuid, is_downloaded=False)
            ).scalars().all()

            total_pending = len(pending)
            print(f"[IMAGE REFRESH] Downloading {total_pending} queued images.")
            for idx, img in enumerate(pending):
                if img.download_url:
                    try:
                        save_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], img.url)
                        _download_image(img.download_url, save_path)
                        img.is_downloaded = True
                        print(f"[IMAGE REFRESH] Downloaded {img.image_type}: {img.url}")
                    except Exception as dl_err:
                        print(f"[IMAGE REFRESH] Failed to download {img.url}: {dl_err}")
                if total_pending > 0:
                    progress = 75 + int(((idx + 1) / total_pending) * 24)
                    cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': progress}, timeout=300)

            db.session.commit()
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'complete', 'progress': 100}, timeout=300)
            print(f"[IMAGE REFRESH] Successfully finished for '{game.name}'")

        except Exception as e:
            db.session.rollback()
            print(f"[IMAGE REFRESH] Exception: {str(e)}")
            import traceback
            traceback.print_exc()
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
            
def delete_game_images(game_uuid):
    with current_app.app_context():
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
        if not game:
            print("Game not found for image deletion.")
            return

        images_to_delete = db.session.execute(select(Image).filter_by(game_uuid=game_uuid)).scalars().all()

        for image in images_to_delete:
            try:
                relative_image_path = image.url.replace('/static/library/images/', '').strip("/")
                image_file_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], relative_image_path)
                image_file_path = os.path.normpath(image_file_path)

                if os.path.exists(image_file_path):
                    os.remove(image_file_path)
                    if not os.path.exists(image_file_path):
                        print(f"Deleted image file: {image_file_path}")
                    else:
                        print(f"Failed to delete image file: {image_file_path}")
                else:
                    print(f"Image file not found: {image_file_path}")

                db.session.delete(image)
            except Exception as e:
                print(f"Error deleting image or database operation failed: {e}")
                db.session.rollback()
                continue  # next image

        try:
            db.session.commit()
            print("All associated images have been deleted.")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing image deletion changes to the database: {e}")
            
def is_scan_job_running():
    """
    Check if there is any scan job with the status 'Running'.
    
    Returns:
        bool: True if there is a running scan job, False otherwise.
    """
    running_scan_job = db.session.execute(select(ScanJob).filter_by(status='Running')).first()
    return running_scan_job is not None
