from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from sharewarez import db
from sharewarez.models import Game, GameRequest, GameRequestUser, User
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.game_requests import (
    REQUEST_STATUSES,
    RESOLVED_STATUSES,
    create_or_join_request,
    create_update_request,
    enrich_request_search,
    fetch_related_editions,
    get_request_settings,
    search_igdb_games,
    update_request_status,
    update_request_preferences,
    withdraw_request,
)
from sharewarez.utils.request_notifications import notify_new_request, notify_request_updated


game_requests_bp = Blueprint('game_requests', __name__)
_request_rate_hits = defaultdict(deque)
_request_rate_lock = Lock()


def _rate_limit_response(scope, limit, window_seconds=60):
    """Small per-process guard; upstream proxy limits can remain stricter."""
    key = (scope, current_user.id)
    now = monotonic()
    with _request_rate_lock:
        hits = _request_rate_hits[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
            response = jsonify({'error': f'Too many requests. Try again in {retry_after} seconds.'})
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            return response
        hits.append(now)
    return None


def _require_enabled():
    if not get_request_settings()['enableGameRequests']:
        abort(404)


@game_requests_bp.route('/requests')
@login_required
def requests_page():
    _require_enabled()
    page = max(request.args.get('page', 1, type=int), 1)
    query = (
        select(GameRequestUser)
        .options(selectinload(GameRequestUser.game_request).selectinload(GameRequest.fulfilled_game))
        .where(GameRequestUser.user_id == current_user.id, GameRequestUser.withdrawn_at.is_(None))
        .order_by(GameRequestUser.created_at.desc())
    )
    pagination = db.paginate(query, page=page, per_page=20, error_out=False)
    settings = get_request_settings()
    active_count = db.session.execute(
        select(func.count(GameRequestUser.id)).join(GameRequest).where(
            GameRequestUser.user_id == current_user.id,
            GameRequestUser.withdrawn_at.is_(None),
            GameRequestUser.satisfied_at.is_(None),
            ~GameRequest.status.in_(RESOLVED_STATUSES),
        )
    ).scalar_one()
    settings['activeRequestCount'] = active_count
    return render_template('requests/requests.html', pagination=pagination, request_settings=settings)


@game_requests_bp.route('/api/requests/search')
@login_required
def request_search():
    _require_enabled()
    if limited := _rate_limit_response('search', 40):
        return limited
    term = (request.args.get('q') or '').strip()
    if len(term) < 2 or len(term) > 100:
        return jsonify({'error': 'Enter between 2 and 100 characters.'}), 400
    results, error = search_igdb_games(term)
    if error:
        return jsonify({'error': error}), 502
    return jsonify({'results': enrich_request_search(results, current_user.id)})


@game_requests_bp.route('/api/requests/editions/<int:igdb_id>')
@login_required
def request_editions(igdb_id):
    _require_enabled()
    if limited := _rate_limit_response('editions', 40):
        return limited
    editions = fetch_related_editions(igdb_id)
    return jsonify({'results': enrich_request_search(editions, current_user.id)})


@game_requests_bp.route('/requests', methods=['POST'])
@login_required
def submit_request():
    _require_enabled()
    if limited := _rate_limit_response('submit', 10):
        return limited
    data = request.get_json(silent=True) or request.form
    igdb_id = data.get('igdb_id')
    if not str(igdb_id or '').isdigit():
        return jsonify({'error': 'A valid IGDB game is required.'}), 400
    existing = db.session.execute(select(GameRequest).filter_by(igdb_id=int(igdb_id))).scalars().first()
    try:
        game_request, _ = create_or_join_request(
            current_user,
            int(igdb_id),
            data.get('note'),
            str(data.get('accept_any_edition', '')).lower() in {'true', '1', 'on', 'yes'},
        )
        log_system_event(f'{current_user.name} requested {game_request.game_name}', event_type='game_request', event_level='information')
        notify_new_request(game_request, joined_existing=existing is not None)
        return jsonify({'message': 'Your request was submitted.', 'request_id': game_request.id}), 201
    except IntegrityError:
        db.session.rollback()
        try:
            game_request, _ = create_or_join_request(
                current_user, int(igdb_id), data.get('note'),
                str(data.get('accept_any_edition', '')).lower() in {'true', '1', 'on', 'yes'},
            )
            notify_new_request(game_request, joined_existing=True)
            return jsonify({'message': 'Your request was joined.', 'request_id': game_request.id}), 201
        except ValueError as error:
            db.session.rollback()
            return jsonify({'error': str(error)}), 400
    except ValueError as error:
        db.session.rollback()
        return jsonify({'error': str(error)}), 400


@game_requests_bp.route('/game_details/<game_uuid>/request-update', methods=['POST'])
@login_required
def submit_update_request(game_uuid):
    _require_enabled()
    if limited := _rate_limit_response('submit', 10):
        return limited
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first() or abort(404)
    data = request.get_json(silent=True) or request.form
    existing = db.session.execute(
        select(GameRequest).where(
            GameRequest.source_game_uuid == game.uuid,
            GameRequest.request_type == 'update',
            ~GameRequest.status.in_(RESOLVED_STATUSES)
        )
    ).scalars().first()
    try:
        game_request, _ = create_update_request(
            current_user,
            game,
            note=data.get('note'),
            target_version=data.get('target_version'),
            reference_url=data.get('reference_url'),
        )
        log_system_event(
            f'{current_user.name} requested update for {game.name}',
            event_type='game_request', event_level='information'
        )
        notify_new_request(game_request, joined_existing=existing is not None)
        return jsonify({'message': 'Your update request was submitted.', 'request_id': game_request.id}), 201
    except IntegrityError:
        db.session.rollback()
        try:
            game_request, _ = create_update_request(
                current_user, game, note=data.get('note'),
                target_version=data.get('target_version'), reference_url=data.get('reference_url'),
            )
            notify_new_request(game_request, joined_existing=True)
            return jsonify({'message': 'Your update request was joined.', 'request_id': game_request.id}), 201
        except ValueError as error:
            db.session.rollback()
            return jsonify({'error': str(error)}), 400
    except ValueError as error:
        db.session.rollback()
        return jsonify({'error': str(error)}), 400


@game_requests_bp.route('/requests/<int:request_id>/withdraw', methods=['POST'])
@login_required
def withdraw(request_id):
    _require_enabled()
    try:
        game_request = withdraw_request(current_user, request_id)
        log_system_event(f'{current_user.name} withdrew request {game_request.game_name}', event_type='game_request')
        flash('Request withdrawn.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('game_requests.requests_page', page=max(request.args.get('page', 1, type=int), 1)))


@game_requests_bp.route('/requests/<int:request_id>/preferences', methods=['POST'])
@login_required
def update_preferences(request_id):
    _require_enabled()
    try:
        update_request_preferences(
            current_user,
            request_id,
            note=request.form.get('note'),
            accept_any_edition=request.form.get('accept_any_edition') == 'on',
        )
        flash('Request preferences updated.', 'success')
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(url_for('game_requests.requests_page', page=max(request.args.get('page', 1, type=int), 1)))


@game_requests_bp.route('/admin/game-requests')
@login_required
@admin_required
def admin_requests():
    page = max(request.args.get('page', 1, type=int), 1)
    status_param = request.args.get('status')
    if status_param is None:
        status = 'pending'
    elif status_param == 'all':
        status = ''
    else:
        status = status_param.strip()
    req_type = (request.args.get('type') or '').strip()
    sort = (request.args.get('sort') or 'newest').strip()
    search_term = (request.args.get('q') or '').strip()[:100]
    query = select(GameRequest).options(selectinload(GameRequest.requesters))
    if status in REQUEST_STATUSES:
        query = query.where(GameRequest.status == status)
    if req_type in {'new_game', 'update'}:
        query = query.where(GameRequest.request_type == req_type)
    if search_term:
        pattern = f'%{search_term}%'
        query = query.where(
            GameRequest.game_name.ilike(pattern)
            | GameRequest.parent_game_name.ilike(pattern)
            | GameRequest.public_response.ilike(pattern)
            | GameRequest.internal_note.ilike(pattern)
            | GameRequest.requesters.any(GameRequestUser.user.has(User.name.ilike(pattern)))
        )
    active_demand = (
        select(func.count(GameRequestUser.id))
        .where(
            GameRequestUser.request_id == GameRequest.id,
            GameRequestUser.withdrawn_at.is_(None),
            GameRequestUser.satisfied_at.is_(None),
        )
        .correlate(GameRequest)
        .scalar_subquery()
    )
    orderings = {
        'newest': (GameRequest.created_at.desc(),),
        'oldest': (GameRequest.created_at.asc(),),
        'updated': (GameRequest.updated_at.desc(),),
        'title': (GameRequest.game_name.asc(),),
        'demand': (active_demand.desc(), GameRequest.created_at.asc()),
    }
    if sort not in orderings:
        sort = 'newest'
    query = query.order_by(*orderings[sort])
    pagination = db.paginate(query, page=page, per_page=24, error_out=False)
    counts = dict(db.session.execute(select(GameRequest.status, func.count(GameRequest.id)).group_by(GameRequest.status)).all())
    type_counts = dict(db.session.execute(select(GameRequest.request_type, func.count(GameRequest.id)).group_by(GameRequest.request_type)).all())
    return render_template(
        'admin/admin_game_requests.html', pagination=pagination,
        statuses=REQUEST_STATUSES, selected_status=status, selected_type=req_type, search_term=search_term,
        status_counts=counts, type_counts=type_counts, selected_sort=sort,
    )


@game_requests_bp.route('/admin/game-requests/<int:request_id>')
@login_required
@admin_required
def admin_request_details(request_id):
    game_request = db.session.execute(
        select(GameRequest)
        .options(
            selectinload(GameRequest.requesters).selectinload(GameRequestUser.user),
            selectinload(GameRequest.requesters).selectinload(GameRequestUser.satisfied_by_game),
            selectinload(GameRequest.fulfilled_game),
            selectinload(GameRequest.source_game),
        )
        .where(GameRequest.id == request_id)
    ).scalars().first() or abort(404)
    alternatives = []
    if game_request.parent_igdb_id:
        alternatives = db.session.execute(
            select(GameRequest)
            .options(selectinload(GameRequest.requesters))
            .where(
                GameRequest.parent_igdb_id == game_request.parent_igdb_id,
                GameRequest.id != game_request.id,
            )
            .order_by(GameRequest.game_name)
        ).scalars().all()
    return render_template(
        'admin/admin_game_request_details.html',
        game_request=game_request,
        alternatives=alternatives,
        statuses=REQUEST_STATUSES,
        return_status=request.args.get('status', ''),
        return_type=request.args.get('type', ''),
        return_search=request.args.get('q', ''),
        return_sort=request.args.get('sort', 'newest'),
        return_page=max(request.args.get('page', 1, type=int), 1),
    )


@game_requests_bp.route('/api/requests/library-games')
@login_required
@admin_required
def request_library_games():
    term = (request.args.get('q') or '').strip()
    if len(term) < 2 or len(term) > 100:
        return jsonify({'results': []})
    games = db.session.execute(
        select(Game)
        .where(Game.name.ilike(f'%{term}%'))
        .order_by(Game.name)
        .limit(20)
    ).scalars().all()
    return jsonify({
        'results': [
            {
                'uuid': game.uuid,
                'name': game.name,
                'version': game.version,
            }
            for game in games
        ]
    })


@game_requests_bp.route('/admin/game-requests/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def admin_update_request(request_id):
    game_request = db.session.get(GameRequest, request_id) or abort(404)
    previous = game_request.status
    previous_public_response = game_request.public_response
    previous_fulfilled_game_uuid = game_request.fulfilled_game_uuid
    try:
        game_request, additionally_satisfied = update_request_status(
            game_request, current_user, request.form.get('status', ''),
            request.form.get('public_response'), request.form.get('internal_note'),
            request.form.get('fulfilled_game_uuid') or None,
        )
        log_system_event(
            f'{current_user.name} changed {game_request.game_name} request from {previous} to {game_request.status}',
            event_type='game_request', event_level='information',
        )
        public_change = (
            previous != game_request.status
            or previous_public_response != game_request.public_response
            or previous_fulfilled_game_uuid != game_request.fulfilled_game_uuid
        )
        if public_change:
            notify_request_updated(game_request, additionally_satisfied or None)
        flash('Game request updated.', 'success')
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(url_for(
        'game_requests.admin_request_details', request_id=request_id,
        status=request.args.get('status', ''), q=request.args.get('q', ''),
        type=request.args.get('type', ''), sort=request.args.get('sort', 'newest'),
        page=request.args.get('page', 1),
    ))
