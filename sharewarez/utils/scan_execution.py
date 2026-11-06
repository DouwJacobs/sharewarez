"""Bounded scan execution with an explicit, persisted result per attempt."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import os

from flask import current_app
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import AllowedFileType, Game, GlobalSettings, Library, ScanJob, UnmatchedFolder
from sharewarez.utils.background_jobs import JobCancelled
from sharewarez.utils.scan_lifecycle import ScanRunError, create_scan_detail, finish_scan
from sharewarez.utils.scan_targets import enumerate_scan_target, resolve_scan_target, validate_scan_candidate


def _check(detail_id, context):
    from sharewarez.utils.shutdown import should_continue_processing

    if not should_continue_processing():
        raise JobCancelled('Scan cancelled due to worker shutdown. No removals performed.')
    if context:
        context.check_cancelled(force=True)
    detail = db.session.get(ScanJob, detail_id, populate_existing=True)
    if detail is None or not detail.is_enabled:
        raise JobCancelled('Scan cancelled by user. No removals performed.')


def _reconcile(u, detail_id, target, extensions, candidates, patterns, library_uuid, context, counts):
    _check(detail_id, context)
    fresh = resolve_scan_target(target.path, target.mode, extensions=extensions)
    if (fresh.device, fresh.inode) != (target.device, target.inode):
        raise ScanRunError('No removals performed: scan target changed during processing.')
    current, complete = enumerate_scan_target(fresh, extensions, *patterns)
    if not complete or not current or {item['full_path'] for item in current} != {item['full_path'] for item in candidates}:
        raise ScanRunError('No removals performed: empty, changed or incomplete candidate listing.')
    u.filesystem_fingerprint(target.path)
    games = db.session.execute(select(Game).where(Game.library_uuid == library_uuid)).scalars().all()
    for game in games:
        if not target.owns_stored_path(game.full_disk_path):
            continue
        extension = os.path.splitext(game.full_disk_path)[1][1:].lower()
        if target.mode == 'files' and extension not in extensions:
            continue
        if target.mode == 'folders' and (game.file_type or extension in extensions):
            continue
        try:
            os.stat(game.full_disk_path)
        except (FileNotFoundError, NotADirectoryError):
            _check(detail_id, context)
            info = os.stat(target.path)
            if (info.st_dev, info.st_ino) != (target.device, target.inode):
                raise ScanRunError('No further removals performed: scan target changed.')
            if not u.remove_from_lib(game.uuid):
                raise ScanRunError('Missing-game cleanup could not persist a removal.')
            counts['removed_count'] += 1
        except OSError:
            raise ScanRunError('No further removals performed: a historical game could not be inspected.')


def scan_and_add_games(folder_path, scan_mode='folders', library_uuid=None, remove_missing=False,
                       existing_job=None, download_missing_images=False, force_updates_extras_scan=False,
                       fetch_hltb=False, force_hltb_refetch=False, *, context=None):
    # Keep the public utilities entry point and its existing injectable provider
    # boundary; all production callers now execute under the durable worker.
    from sharewarez import utilities as u

    if not existing_job and u.is_scan_job_running():
        raise ScanRunError('A scan is already in progress.')
    library = db.session.get(Library, library_uuid)
    if library is None:
        raise ScanRunError('Library not found.')
    options = dict(remove_missing=remove_missing, download_missing_images=download_missing_images,
                   force_updates_extras_scan=force_updates_extras_scan, fetch_hltb=fetch_hltb,
                   force_hltb_refetch=force_hltb_refetch)
    detail = existing_job or create_scan_detail(folder_path, scan_mode, library_uuid, options)
    detail_id = detail.id
    counts = dict(total_folders=0, folders_success=0, folders_unmatched=0, folders_failed=0, removed_count=0)
    errors = []
    partial_work = False
    try:
        _check(detail_id, context)
        settings = db.session.execute(select(GlobalSettings).execution_options(populate_existing=True)).scalars().first()
        extensions = [ext.lower() for ext in db.session.execute(select(AllowedFileType.value)).scalars()]
        if not extensions:
            raise ScanRunError('No allowed file types configured. No removals performed.')
        target = resolve_scan_target(folder_path, scan_mode, extensions=extensions)
        patterns = u.load_scanning_filter_patterns()
        candidates, complete = enumerate_scan_target(target, extensions, *patterns)
        counts['total_folders'] = len(candidates)
        if not complete:
            errors.append('Incomplete filesystem enumeration. No removals performed.')
        settings_dict = {key: getattr(settings, key, False) if settings else False for key in ('use_local_metadata', 'write_local_metadata', 'use_local_images')}
        settings_dict['local_metadata_filename'] = settings.local_metadata_filename if settings else u.DEFAULT_LOCAL_METADATA_FILENAME
        updates = bool(settings and settings.enable_game_updates)
        extras = bool(settings and settings.enable_game_extras)
        update_name = settings.update_folder_name if settings else 'updates'
        extra_name = settings.extras_folder_name if settings else 'extras'
        hltb_enabled = bool(settings and settings.enable_hltb_integration)
        workers = max(1, min(8, int(settings.scan_thread_count or 1))) if settings else 1
        limiter = u.IGDBRateLimiter()
        app = current_app._get_current_object()

        def process(candidate):
            with app.app_context():
                matched = False
                try:
                    _check(detail_id, context)
                    path, name = candidate['full_path'], candidate['name']
                    validate_scan_candidate(target, path)
                    game = db.session.execute(select(Game).where(Game.library_uuid == library_uuid, Game.full_disk_path == path)).scalars().first()
                    matched = game is not None
                    if not matched:
                        limiter.acquire()
                        try:
                            _check(detail_id, context)
                            matched = u.process_game_with_fallback(name, path, detail_id, library_uuid,
                                fetch_hltb=bool(fetch_hltb and hltb_enabled), settings=settings_dict)
                        finally:
                            limiter.release()
                    if not matched:
                        unmatched = db.session.execute(select(UnmatchedFolder.id).where(UnmatchedFolder.library_uuid == library_uuid, UnmatchedFolder.folder_path == path)).first()
                        if not unmatched:
                            raise ScanRunError('Provider did not persist a matched or unmatched result.')
                        return 'unmatched', None
                    _check(detail_id, context)
                    u._scan_enabled_supplemental_content(name, path, library_uuid, updates, update_name, extras, extra_name)
                    if game and force_hltb_refetch and hltb_enabled:
                        from sharewarez.utils.hltb import update_game_hltb_sync
                        update_game_hltb_sync(game.uuid, game.name)
                    return 'matched', None
                except JobCancelled:
                    return 'cancelled', None
                except Exception as exc:
                    db.session.rollback()
                    return ('partial' if matched else 'failed'), str(exc)
                finally:
                    db.session.remove()

        def record(candidate, result):
            nonlocal partial_work
            kind, error = result
            if kind == 'cancelled':
                return True
            if kind == 'partial':
                partial_work = True
                kind = 'failed'
            counts[{'matched': 'folders_success', 'unmatched': 'folders_unmatched', 'failed': 'folders_failed'}[kind]] += 1
            if error:
                errors.append(f"{candidate['name']}: {error}")
            row = db.session.get(ScanJob, detail_id, populate_existing=True)
            for key, value in counts.items():
                setattr(row, key, value)
            row.current_processing = f"Processed: {candidate['name']}"[:255]
            row.last_progress_update = datetime.now(timezone.utc)
            db.session.commit()
            return False

        cancelled = False
        if workers == 1:
            for candidate in candidates:
                _check(detail_id, context)
                cancelled = record(candidate, process(candidate))
                if cancelled:
                    break
                if context:
                    context.heartbeat(message=f"Processed {sum(counts[key] for key in ('folders_success', 'folders_unmatched', 'folders_failed'))}/{len(candidates)}")
        else:
            # At most one unit per worker is submitted. Once cancellation is
            # observed, drain started units and never schedule another candidate.
            iterator = iter(candidates)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending = {}
                def fill():
                    nonlocal cancelled
                    while len(pending) < workers:
                        try:
                            _check(detail_id, context)
                        except JobCancelled:
                            cancelled = True
                            break
                        candidate = next(iterator, None)
                        if candidate is None:
                            break
                        pending[pool.submit(process, candidate)] = candidate
                fill()
                while pending:
                    done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    for future in done:
                        cancelled = record(pending.pop(future), future.result()) or cancelled
                    try:
                        _check(detail_id, context)
                        if context:
                            context.heartbeat(message='Scanning library')
                    except JobCancelled:
                        cancelled = True
                    if not cancelled:
                        fill()
        if cancelled:
            raise JobCancelled('Scan cancelled. No removals performed.')
        _check(detail_id, context)
        if download_missing_images and not errors:
            from sharewarez.utils.game_core import process_missing_images_for_scan
            images = process_missing_images_for_scan(library_uuid, app)
            if not images.get('success'):
                errors.append('Missing images processing failed.')
        if errors:
            raise ScanRunError('; '.join(errors))
        if remove_missing and candidates:
            _reconcile(u, detail_id, target, extensions, candidates, patterns, library_uuid, context, counts)
        _check(detail_id, context)
        message = '' if candidates else 'No games found. No removals performed: empty candidate listing.'
        return finish_scan(detail_id, 'completed', message, counts)
    except JobCancelled as exc:
        db.session.rollback()
        message = str(exc)
        if counts['removed_count']:
            message = 'No further removals performed: scan cancelled. ' + message.replace('No removals performed', 'No further removals performed')
        elif 'No removals performed' not in message:
            message = 'No removals performed: scan cancelled. ' + message
        finish_scan(detail_id, 'cancelled', message, counts)
        raise
    except Exception as exc:
        db.session.rollback()
        outcome = 'partial' if partial_work or counts['folders_success'] + counts['folders_unmatched'] else 'failed'
        message = str(exc)
        if 'removals performed' not in message.lower():
            message = f"{'No further removals performed' if counts['removed_count'] else 'No removals performed'}: scan failed. {message}"
        finish_scan(detail_id, outcome, message, counts)
        raise ScanRunError(message) from exc
