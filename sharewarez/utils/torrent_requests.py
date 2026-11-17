"""Durable request-only catalogue lookup and atomic fulfilment."""
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlsplit

from sqlalchemy import JSON, cast, select
from werkzeug.datastructures import FileStorage

from sharewarez import db
from sharewarez.models import BackgroundJob, GameRequest, GameRequestUser, GlobalSettings, Library, User
from sharewarez.utils.background_jobs import enqueue
from sharewarez.utils.game_requests import _existing_game
from sharewarez.utils.torrent_service import attach_prepared, discard_attachments, prepare_source


def configuration():
    record = db.session.execute(select(GlobalSettings).order_by(GlobalSettings.id)).scalars().first()
    return dict(record.settings or {}) if record else {}


def eligible(game_request, user, settings):
    return bool(
        settings.get('autoFulfillTorrentRequests') is True
        and settings.get('enableGameRequests', True)
        and user and user.state and user.can_auto_fulfill_torrent_requests
        and game_request.request_type == 'new_game'
        and game_request.status == 'pending'
        and any(link.user_id == user.id and link.withdrawn_at is None for link in game_request.requesters)
    )


def allowed(game_request, user, settings, selected_entry=None):
    if selected_entry is None:
        return eligible(game_request, user, settings)
    return bool(user and user.state and user.role == 'admin'
        and settings.get('autoFulfillTorrentRequests') is True
        and game_request.request_type == 'new_game' and game_request.status == 'pending'
        and game_request.active_requesters
        and selected_entry.get('source_url') in settings.get('torrentCatalogueUrls', '').split())


def queue_lookup(game_request, user, *, retry=False, selected_entry=None):
    # Serialize concurrent joins and retries; the request owns one outstanding lookup.
    db.session.flush()
    game_request = db.session.execute(select(GameRequest).where(GameRequest.id == game_request.id)
        .with_for_update().execution_options(populate_existing=True)).scalar_one()
    db.session.expire(game_request, ['requesters'])
    if not allowed(game_request, user, configuration(), selected_entry):
        return None
    active_jobs = db.session.execute(select(BackgroundJob).where(
        BackgroundJob.task_name == 'requests.torrent_lookup',
        BackgroundJob.status.in_(['queued', 'running']))).scalars()
    if any(job.payload.get('request_id') == game_request.id for job in active_jobs):
        return None
    if game_request.torrent_lookup_status and not retry:
        return None
    payload = {'request_id': game_request.id, 'user_id': user.id}
    if selected_entry is not None:
        payload['selected_entry'] = selected_entry
    job = enqueue('requests.torrent_lookup', payload,
                  created_by_id=user.id, commit=False)
    game_request.torrent_lookup_status = 'queued'
    game_request.torrent_lookup_message = 'Waiting for catalogue lookup.'
    return job


def outcome(game_request, status, message, **details):
    game_request.torrent_lookup_status = status
    game_request.torrent_lookup_message = message[:2000]
    db.session.commit()
    return {'status': status, 'request_id': game_request.id, **details}


def candidate_job(request_id):
    return db.session.execute(select(BackgroundJob).where(
        BackgroundJob.task_name == 'requests.torrent_lookup',
        cast(BackgroundJob.payload, JSON)['request_id'].as_integer() == request_id,
        BackgroundJob.status == 'completed',
    ).order_by(BackgroundJob.created_at.desc()).limit(1)).scalar_one_or_none()


def execute_lookup(context, payload):
    from sharewarez.utils.torrent_catalogues import fetch_catalogue, fetch_bytes, match_catalogues
    request_id = payload['request_id']
    game_request = db.session.get(GameRequest, request_id)
    if game_request is None:
        return {'status': 'skipped'}
    if game_request.status == 'fulfilled':
        return {'status': 'fulfilled', 'game_uuid': game_request.fulfilled_game_uuid}
    user = db.session.get(User, payload['user_id'])
    settings = configuration()
    selected = payload.get('selected_entry')
    if not allowed(game_request, user, settings, selected):
        return outcome(game_request, 'skipped', 'Request, permission, or configuration changed.')
    title = game_request.game_name
    game_request.torrent_lookup_status = 'looking_up'
    db.session.commit()
    urls = list(dict.fromkeys(settings.get('torrentCatalogueUrls', '').split()))[:5]
    catalogues, errors = [], []
    for index, url in enumerate([] if selected else urls):
        context.heartbeat(5 + index * 10, 'Reading torrent catalogue')
        try:
            catalogues.append(fetch_catalogue(url))
        except (ValueError, OSError) as exc:
            errors.append(type(exc).__name__)
    if selected:
        match = {'status': 'matched', 'entry': selected}
    elif settings.get('torrentPreferLatestUpload') is True:
        match = match_catalogues(title, catalogues, prefer_latest_upload=True)
    else:
        match = match_catalogues(title, catalogues)
    if match['status'] != 'matched':
        if errors:
            outcome(game_request, 'source_error', 'A catalogue could not be read. Check source settings or retry later.')
            raise RuntimeError('Torrent catalogue unavailable')
        if match['status'] == 'ambiguous':
            titles = '; '.join(item['title'] for item in match.get('candidates', [])[:4])
            return outcome(game_request, 'ambiguous',
                'Multiple matching releases need admin review. ' + titles,
                candidates=match.get('candidates', []))
        return outcome(game_request, match['status'], 'No confident torrent release matched this request.')
    entry = match['entry']
    prepared = []
    for uri in entry['uris'][:30]:
        try:
            label = (entry['source_name'] + ': ' + entry['title'])[:160]
            if uri.startswith('magnet:'):
                candidate = prepare_source(label, uri, public=True)
            elif urlsplit(uri).path.lower().endswith('.torrent'):
                data = fetch_bytes(uri, 10 * 1024 * 1024)
                candidate = prepare_source(label, upload=FileStorage(BytesIO(data), filename='release.torrent'), public=True)
            else:
                continue
            if candidate[0]['fingerprint'] not in {item[0]['fingerprint'] for item in prepared}:
                prepared.append(candidate)
        except (ValueError, OSError):
            continue
    if not prepared:
        return outcome(game_request, 'source_error', 'Matched release contains no usable public magnet or torrent file.')
    context.check_cancelled(force=True)
    # Drop stale ORM snapshots after remote work; recheck everything under locks.
    db.session.rollback()
    from sharewarez.utils.torrent_storage import acquire_source_mutation_lock
    acquire_source_mutation_lock()
    game_request = db.session.execute(select(GameRequest).where(GameRequest.id == request_id)
        .with_for_update().execution_options(populate_existing=True)).scalar_one()
    if game_request.status == 'fulfilled':
        return {'status': 'fulfilled', 'game_uuid': game_request.fulfilled_game_uuid}
    user = db.session.execute(select(User).where(User.id == payload['user_id']).with_for_update()
        .execution_options(populate_existing=True)).scalar_one_or_none()
    record = db.session.execute(select(GlobalSettings).order_by(GlobalSettings.id).with_for_update()
        .execution_options(populate_existing=True)).scalars().first()
    latest = dict(record.settings or {}) if record else {}
    if not allowed(game_request, user, latest, selected) or latest != settings:
        return outcome(game_request, 'skipped', 'Request, permission, or configuration changed during lookup.')
    library = db.session.get(Library, latest.get('torrentDestinationLibraryUuid'))
    if library is None:
        return outcome(game_request, 'source_error', 'Choose a destination library in Requests settings.')
    keys = []
    try:
        game = _existing_game(game_request.metadata_provider, game_request.provider_game_id)
        if game is None:
            from sharewarez.utils.game_core import create_game_instance_from_metadata
            game = create_game_instance_from_metadata({
                'provider': game_request.metadata_provider, 'provider_game_id': game_request.provider_game_id,
                'provider_url': game_request.provider_url, 'game_name': game_request.game_name,
                'summary': game_request.summary, 'first_release_date': game_request.first_release_date,
                'cover_url': game_request.cover_url, 'platforms': game_request.platforms or [],
            }, None, 0, library.uuid)
            game.edition_name = game_request.edition_name
        keys = attach_prepared(game, prepared, user.id if selected else None)
        now = datetime.now(timezone.utc)
        game_request.status = 'fulfilled'
        game_request.fulfilled_game = game
        game_request.handled_by_user_id = user.id if selected else None
        game_request.resolved_at = now
        game_request.torrent_lookup_status = 'fulfilled'
        reason = ('Admin selected ' if selected else 'Automatically selected most recent upload '
                  if match.get('selection_reason') == 'latest_upload' else 'Automatically matched ')
        game_request.torrent_lookup_message = (reason
            + entry['title'] + ' from ' + entry['source_url'])[:2000]
        satisfied = list(game_request.requesters)
        if game_request.provider_parent_id:
            satisfied += db.session.execute(select(GameRequestUser).join(GameRequest).where(
                GameRequest.metadata_provider == game_request.metadata_provider,
                GameRequest.provider_parent_id == game_request.provider_parent_id,
                GameRequest.id != game_request.id,
                GameRequest.status.in_(['pending', 'reviewing', 'planned']),
                GameRequestUser.accept_any_edition.is_(True),
                GameRequestUser.satisfied_at.is_(None),
                GameRequestUser.withdrawn_at.is_(None),
            )).scalars().all()
        for link in satisfied:
            if link.withdrawn_at is None:
                link.satisfied_at = now
                link.satisfied_by_game_uuid = game.uuid
        from sharewarez.utils.image_jobs import enqueue_image_refresh
        enqueue_image_refresh(game.uuid, expected_igdb_id=game.igdb_id, commit=False)
        enqueue('requests.torrent_enrich', {'game_uuid': game.uuid}, commit=False)
        # Notification records/jobs commit with fulfilment so restarts cannot lose updates.
        from sharewarez.utils.request_notifications import notify_request_updated
        notify_request_updated(game_request, satisfied, commit=False)
        db.session.commit()
        keys = []
        return {'status': 'fulfilled', 'game_uuid': game.uuid}
    except Exception:
        db.session.rollback()
        discard_attachments(keys)
        raise
