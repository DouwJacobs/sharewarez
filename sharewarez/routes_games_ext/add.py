import os
import json
from flask import render_template, redirect, url_for, flash, session, request, current_app
from flask_login import login_required, current_user
from sharewarez.forms import AddGameForm
from sharewarez.models import Game, GameExternalIdentity, Library, UnmatchedFolder, Category, Developer, Publisher
from sharewarez.metadata_files import DEFAULT_LOCAL_METADATA_FILENAME
from sharewarez.utils.functions import read_first_nfo_content, PLATFORM_IDS
from sharewarez.utils.auth import admin_required
from sharewarez.utils.scanning import is_scan_job_running
from sharewarez.utils.image_jobs import enqueue_image_refresh
from sharewarez.utilities import refresh_game_metadata_and_updates
from sharewarez.utils.metadata_provenance import EDITABLE_PROVIDER_FIELDS, mark_manual_changes
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.security import is_safe_path, get_allowed_base_directories, sanitize_path_for_logging
from sharewarez.utils.functions import sanitize_string_input
from sharewarez.utils.game_core import check_existing_game_by_igdb_id
from sharewarez.utils.tags import assign_game_tags
from sharewarez import db
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from uuid import uuid4, UUID
from werkzeug.exceptions import RequestEntityTooLarge

from . import games_bp
from sharewarez.utils.torrent_service import prepare_form_sources, attach_prepared, discard_attachments
from sharewarez.utils.torrent_storage import acquire_source_mutation_lock


@games_bp.route('/add_game_manual', methods=['GET', 'POST'])
@login_required
@admin_required
def add_game_manual():
    if request.method == 'POST':
        acquire_source_mutation_lock()
    submitted_mode = request.form.get('source_mode') if request.method == 'POST' else request.args.get('source_mode')
    if submitted_mode != 'torrent' and is_scan_job_running():
        flash('Cannot add a new game while a scan job is running. Please try again later.', 'error')
        log_system_event(
            f"Admin {current_user.name} attempted to add game while scan job is running",
            event_type='security',
            event_level='warning'
        )
        
        # Determine redirection based from_unmatched
        from_unmatched = request.args.get('from_unmatched', 'false') == 'true'
        if from_unmatched:
            return redirect(url_for('main.admin_scan_management', active_tab='unmatched'))
        else:
            return redirect(url_for('library.library'))
    
    from sharewarez.utils.manual_scan import resolve_manual_candidate
    generation = request.args.get('selection_generation') or request.form.get('selection_generation')
    candidate_path = request.args.get('candidate_path') or request.form.get('candidate_path')
    selection = None
    if generation:
        try:
            selection = resolve_manual_candidate(generation, candidate_path, request.form.get('library_uuid') if request.method == 'POST' else request.args.get('library_uuid'))
            if request.method == 'POST':
                if request.form.get('full_disk_path') != selection['full_path'] or request.form.get('selection_generation', generation) != generation or request.form.get('candidate_path', candidate_path) != candidate_path:
                    raise ValueError('The selected candidate changed. List games again.')
        except (ValueError, OSError) as exc:
            flash(f'Manual selection is stale: {exc}', 'warning')
            return redirect(url_for('main.admin_scan_management', active_tab='manual'))

    full_disk_path = selection['full_path'] if selection else request.args.get('full_disk_path', None)
    library_uuid = selection['library_uuid'] if selection else request.args.get('library_uuid') or session.get('selected_library_uuid')
    from_unmatched = request.args.get('from_unmatched', 'false') == 'true'  # Detect origin
    game_name = os.path.basename(full_disk_path) if full_disk_path else ''

    form = AddGameForm()
    if selection:
        form.selection_generation.data = generation
        form.candidate_path.data = candidate_path
        form.full_disk_path.render_kw = {'readonly': True}

    # Populate the choices for the library_uuid field
    form.library_uuid.choices = [(str(library.uuid), library.name) for library in db.session.execute(select(Library).order_by(Library.name)).scalars().all()]
    log_system_event(
        f"Add game form loaded with {len(form.library_uuid.choices)} library options",
        event_type='form',
        event_level='debug'
    )

    # Fetch library details for displaying on the form
    # Use the library_uuid already set from args or session (don't overwrite it!)
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if library:
        library_name = library.name
        platform_name = library.platform.name
        platform_id = PLATFORM_IDS.get(library.platform.name)
    else:
        library_name = platform_name = ''
        platform_id = None
    
    if request.method == 'GET':
        form.entry_uuid.data = str(uuid4())
        if request.args.get('source_mode') == 'torrent':
            form.source_mode.data = 'torrent'
        if full_disk_path:
            form.full_disk_path.data = full_disk_path
            form.name.data = game_name
        if library_uuid:
            form.library_uuid.data = library_uuid
    
    if form.validate_on_submit():
        try:
            entry_uuid = str(UUID(form.entry_uuid.data)) if form.entry_uuid.data else str(uuid4())
        except (ValueError, TypeError):
            flash('Invalid game submission. Reload the form and try again.', 'error')
            return redirect(url_for('games.add_game_manual'))
        existing_entry = db.session.execute(select(Game).where(Game.uuid == entry_uuid)).scalar_one_or_none()
        if existing_entry:
            return redirect(url_for('games.game_details', game_uuid=existing_entry.uuid))
        prepared_sources = []
        try:
            prepared_sources = prepare_form_sources(request.form, request.files)
            if form.source_mode.data == 'torrent':
                form.full_disk_path.data = None
                if not prepared_sources:
                    raise ValueError('Add at least one magnet link or torrent file.')
            elif not (form.full_disk_path.data or '').strip():
                raise ValueError('A local game requires a disk path.')
        except (ValueError, RequestEntityTooLarge) as exc:
            form.source_mode.errors = list(form.source_mode.errors) + [str(exc)]
            return render_template('admin/admin_game_identify.html', form=form, action='add', library_name=library_name, platform_name=platform_name, platform_id=platform_id, torrent_source_error=str(exc), torrent_source_error_index=getattr(exc, 'row_index', None)), 413 if isinstance(exc, RequestEntityTooLarge) else 200
        # Validate full_disk_path security
        allowed_bases = get_allowed_base_directories(current_app)
        if form.full_disk_path.data and not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'error')
            return render_template('admin/admin_game_identify.html', form=form, library_uuid=library_uuid, library_name=library_name, platform_name=platform_name, platform_id=platform_id)

        is_safe, error_message = is_safe_path(form.full_disk_path.data, allowed_bases) if form.full_disk_path.data else (True, '')
        if not is_safe:
            sanitized_path = sanitize_path_for_logging(form.full_disk_path.data)
            log_system_event(
                f"Path validation failed for admin {current_user.name}: {sanitized_path} - {error_message}",
                event_type='security',
                event_level='warning'
            )
            flash(f"Access denied: {error_message}", 'error')
            return render_template('admin/admin_game_identify.html', form=form, library_uuid=library_uuid, library_name=library_name, platform_name=platform_name, platform_id=platform_id)

        is_custom_game = form.manual_identity.data == '1'
        if not is_custom_game and form.igdb_id.data is None:
            form.igdb_id.errors.append('Choose an IGDB game or use Custom game.')
            return render_template('admin/admin_game_identify.html', form=form, library_uuid=library_uuid, library_name=library_name, platform_name=platform_name, platform_id=platform_id)
        
        # For custom games, skip IGDB ID check
        if not is_custom_game and check_existing_game_by_igdb_id(form.igdb_id.data):
            flash('A game with this IGDB ID already exists.', 'error')
            return render_template('admin/admin_game_identify.html', form=form, library_uuid=library_uuid, library_name=library_name, platform_name=platform_name, platform_id=platform_id)
        
        game_uuid = entry_uuid
        identity_provider = 'local' if is_custom_game else 'igdb'
        identity_external_id = game_uuid if is_custom_game else str(form.igdb_id.data)
        new_game = Game(
            uuid=game_uuid,
            igdb_id=None if is_custom_game else form.igdb_id.data,
            name=form.name.data,
            summary=form.summary.data,
            storyline=form.storyline.data,
            install_instructions=form.install_instructions.data,
            version=(form.version.data or '').strip() or None,
            edition_name=(form.edition_name.data or '').strip() or None,

            url=form.url.data,
            full_disk_path=form.full_disk_path.data,
            file_type=selection.get('file_type') if selection else None,
            # Set default cover for custom games
            cover=url_for('static', filename='newstyle/default_cover.jpg') if is_custom_game else None,
            category=form.category.data,
            status=form.status.data,
            first_release_date=form.first_release_date.data,
            aggregated_rating=form.aggregated_rating.data,
            video_urls=form.video_urls.data,
            library_uuid=form.library_uuid.data
        )
        new_game.external_identities.append(GameExternalIdentity(
            provider=identity_provider,
            external_id=identity_external_id,
            canonical=True,
        ))
        new_game.genres = form.genres.data
        new_game.game_modes = form.game_modes.data
        new_game.themes = form.themes.data
        new_game.platforms = form.platforms.data
        new_game.player_perspectives = form.player_perspectives.data

        try:
            assign_game_tags(new_game, form.tags.data)
        except ValueError as e:
            flash(str(e), 'error')
            return render_template('admin/admin_game_identify.html', form=form, library_uuid=library_uuid, library_name=library_name, platform_name=platform_name, platform_id=platform_id)

        # Handle developer with input sanitization
        if form.developer.data and form.developer.data != 'Not Found':
            sanitized_developer_name = sanitize_string_input(form.developer.data, 255)
            if sanitized_developer_name:
                developer = db.session.execute(select(Developer).filter_by(name=sanitized_developer_name)).scalars().first()
                if not developer:
                    developer = Developer(name=sanitized_developer_name)
                    db.session.add(developer)
                    db.session.flush() 
                new_game.developer = developer

        # Handle publisher with input sanitization
        if form.publisher.data and form.publisher.data != 'Not Found':
            sanitized_publisher_name = sanitize_string_input(form.publisher.data, 255)
            if sanitized_publisher_name:
                publisher = db.session.execute(select(Publisher).filter_by(name=sanitized_publisher_name)).scalars().first()
                if not publisher:
                    publisher = Publisher(name=sanitized_publisher_name)
                    db.session.add(publisher)
                    db.session.flush()
                new_game.publisher = publisher
        new_game.nfo_content = read_first_nfo_content(form.full_disk_path.data) if form.full_disk_path.data else None

        attachment_keys = []
        try:
            db.session.add(new_game)
            attachment_keys = attach_prepared(new_game, prepared_sources, current_user.id)
            
            # Handle unmatched folder deletion in same transaction for consistency
            unmatched_folder = None
            if full_disk_path: 
                unmatched_folder = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=full_disk_path)).scalars().first()
                if unmatched_folder:
                    db.session.delete(unmatched_folder)
            
            if not is_custom_game:
                enqueue_image_refresh(new_game.uuid, expected_igdb_id=new_game.igdb_id,
                                      audit_user_id=current_user.id, commit=False)
            # Commit the game, sources, and durable artwork request together.
            db.session.commit()
            attachment_keys = []  # Committed attachments must survive later UI/artwork failures.

            if not is_custom_game:
                # Complete provider relationships/classifications as well as scalar
                # fields. Submitted values remain authoritative when an admin edits
                # the populated form before saving.
                try:
                    manual_fields = json.loads(form.metadata_manual_fields.data or '[]')
                    manual_fields = set(manual_fields) if isinstance(manual_fields, list) and all(isinstance(item, str) for item in manual_fields) else set()
                except (ValueError, TypeError):
                    manual_fields = set()
                tracking_active = form.metadata_tracking_active.data == '1'
                def preserve_field(field, populated):
                    return field in manual_fields if tracking_active else populated or field in manual_fields
                submitted_values = {field: getattr(new_game, field) for field in EDITABLE_PROVIDER_FIELDS
                                    if field in request.form and preserve_field(field, getattr(new_game, field) not in (None, ''))}
                submitted_companies = {field: getattr(new_game, field) for field in ('developer', 'publisher')
                                       if field in request.form and preserve_field(field, getattr(new_game, field) is not None)}
                submitted_classifications = {field: list(getattr(new_game, field)) for field in
                                             ('genres', 'themes', 'game_modes', 'platforms', 'player_perspectives')
                                             if preserve_field(field, bool(request.form.getlist(field)))}
                try:
                    refresh_game_metadata_and_updates(new_game.uuid)
                    provider_values = {field: getattr(new_game, field) for field in EDITABLE_PROVIDER_FIELDS}
                    submitted_date = submitted_values.get('first_release_date')
                    provider_date = provider_values.get('first_release_date')
                    if submitted_date and provider_date and submitted_date.date() == provider_date.date():
                        # The editor owns a calendar date, not a database timezone offset.
                        provider_values['first_release_date'] = submitted_date
                    for field, value in {**submitted_values, **submitted_companies, **submitted_classifications}.items():
                        setattr(new_game, field, value)
                    mark_manual_changes(new_game, provider_values)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    for field, value in {**submitted_values, **submitted_companies, **submitted_classifications}.items():
                        setattr(new_game, field, value)
                    db.session.commit()
                    current_app.logger.warning('Metadata enrichment failed for newly added game %s', new_game.uuid)
                    flash('Game saved. Metadata enrichment could not finish; use Save & refresh to retry.', 'warning')

            # After successful commit, write local metadata file if enabled
            from sharewarez.utils.local_metadata import write_local_metadata
            from sharewarez.models import GlobalSettings

            settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
            print(f"[LOCAL METADATA] Settings check - settings exists: {settings is not None}, write_local_metadata: {settings.write_local_metadata if settings else 'N/A'}")

            if settings and settings.write_local_metadata and new_game.full_disk_path:
                metadata_filename = (
                    settings.local_metadata_filename or DEFAULT_LOCAL_METADATA_FILENAME
                )
                success = write_local_metadata(
                    full_disk_path=form.full_disk_path.data,
                    game_title=form.name.data,
                    manually_verified=True,
                    filename=metadata_filename,
                    install_instructions=form.install_instructions.data,
                    game_version=(form.version.data or '').strip() or None,
                    provider=identity_provider,
                    external_id=identity_external_id,
                )

                if success:
                    flash(f'Metadata file ({metadata_filename}) saved to game folder for future scans.', 'info')
                    log_system_event(
                        f"Local metadata written for game '{form.name.data}' at {sanitize_path_for_logging(form.full_disk_path.data)}",
                        event_type='metadata',
                        event_level='information'
                    )
                else:
                    flash(f'Warning: Could not write metadata file to game folder (check permissions).', 'warning')
                    log_system_event(
                        f"Failed to write local metadata for game '{form.name.data}' at {sanitize_path_for_logging(form.full_disk_path.data)}",
                        event_type='metadata',
                        event_level='warning'
                    )

            from sharewarez.utils.enrichment_policy import enrich_manual_candidate
            enrich_manual_candidate(new_game, selection)

            flash('Game added successfully.', 'success')
            log_system_event(
                f"Game '{game_name}' added manually by admin {current_user.name}" +
                (f" (removed from unmatched list)" if unmatched_folder else ""),
                event_type='game',
                event_level='information'
            )
            
            if from_unmatched:
                return redirect(url_for('main.admin_scan_management', active_tab='unmatched'))
            else:
                return redirect(url_for('games.game_details', game_uuid=new_game.uuid))
        except SQLAlchemyError as e:
            db.session.rollback()
            discard_attachments(attachment_keys)
            log_system_event(
                f"Database error adding game by admin {current_user.name}: {type(e).__name__}",
                event_type='error',
                event_level='error'
            )
            flash('An error occurred while adding the game. Please try again.', 'error')
    else:
        if form.errors:
            log_system_event(
                f"Form validation failed for admin {current_user.name} adding game: {len(form.errors)} errors",
                event_type='form',
                event_level='warning'
            )
    return render_template(
        'admin/admin_game_identify.html',
        form=form,
        from_unmatched=from_unmatched,
        action="add",
        library_uuid=library_uuid,
        library_name=library_name,
        platform_name=platform_name,
        platform_id=platform_id
    )
