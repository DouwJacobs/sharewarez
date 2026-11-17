"""Authorized torrent source actions. No torrent network operations."""
from io import BytesIO
from flask import abort, jsonify, request, send_file, url_for, render_template, redirect, flash, current_app
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sharewarez import db
from sharewarez.models import Game, GameTorrentSource, TorrentSourceAccess, UnmatchedFolder
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.torrent_service import prepare_source, attach_prepared, discard_attachments, confirm_hash_variants
from sharewarez.utils.torrent_storage import verified_attachment, acquire_source_mutation_lock
from . import games_bp


def source_data():
    data = request.get_json(silent=True) if request.is_json else request.form
    if data is None:
        return {}
    if not hasattr(data, 'get'):
        abort(400, description='Source data must be an object.')
    return data


@games_bp.route('/games/attach-local/<folder_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def attach_local_candidate(folder_id):
    import os
    from sharewarez.utils.security import is_safe_path, get_allowed_base_directories
    from sharewarez.utils.functions import get_folder_size_in_bytes_updates
    folder = db.session.get(UnmatchedFolder, folder_id) or abort(404)
    game = db.session.execute(select(Game).where(Game.uuid == folder.candidate_game_uuid).with_for_update()).scalar_one_or_none() or abort(404)
    if request.method == 'GET':
        return render_template('admin/attach_local_candidate.html', folder=folder, game=game)
    safe, _ = is_safe_path(folder.folder_path, get_allowed_base_directories(current_app))
    if game.full_disk_path or not safe or not os.path.exists(folder.folder_path):
        flash('The local files cannot be attached. Review the existing path and mount configuration.', 'error')
        return redirect(url_for('games.attach_local_candidate', folder_id=folder.id))
    conflict = db.session.execute(select(Game).where(Game.full_disk_path == folder.folder_path, Game.uuid != game.uuid)).scalar_one_or_none()
    if conflict:
        abort(409, description='This local path is already assigned to another game.')
    game.full_disk_path = folder.folder_path
    game.size = get_folder_size_in_bytes_updates(folder.folder_path)
    db.session.delete(folder)
    db.session.commit()
    log_system_event(f'Local files attached to game {game.uuid} actor {current_user.id}', event_type='audit')
    return redirect(url_for('games.game_details', game_uuid=game.uuid))


def source_for(game_uuid, source_id):
    return db.session.execute(select(GameTorrentSource).where(
        GameTorrentSource.id == source_id, GameTorrentSource.game_uuid == game_uuid
    )).scalar_one_or_none() or abort(404)


def describe(source):
    result = dict(id=source.id, label=source.label, kind=source.kind,
                  payload_bytes=source.payload_bytes, revision=source.revision)
    action = 'torrent_magnet' if source.kind == 'magnet' else 'torrent_file'
    result['action_url'] = url_for('games.' + action, game_uuid=source.game_uuid, source_id=source.id)
    return result


@games_bp.after_request
def protect_source_responses(response):
    if '/torrent-sources' in request.path:
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@games_bp.route('/games/<game_uuid>/torrent-sources', methods=['GET', 'POST'])
@login_required
def torrent_sources(game_uuid):
    if request.method == 'GET':
        game = db.session.execute(select(Game).where(Game.uuid == game_uuid)).scalar_one_or_none() or abort(404)
        return jsonify([describe(source) for source in game.torrent_sources])
    if current_user.role != 'admin':
        abort(403)
    game = acquire_source_mutation_lock(game_uuid) or abort(404)
    data = source_data()
    keys = []
    try:
        prepared = prepare_source(data.get('label'), data.get('magnet', ''), request.files.get('file'),
                                  data.get('public') in (True, '1'))
        existing = next((s for s in game.torrent_sources if s.fingerprint == prepared[0]['fingerprint']), None)
        if existing:
            return jsonify(describe(existing)), 200
        confirm_hash_variants([prepared], data.get('keep_separate') in (True, '1'), game_uuid=game.uuid)
        keys = attach_prepared(game, [prepared], current_user.id)
        db.session.flush()
        source = game.torrent_sources[-1]
        result = describe(source)
        db.session.commit()
        keys = []
        log_system_event(f'Torrent source added: {source.id} game {game_uuid} actor {current_user.id}', event_type='audit')
        return jsonify(result), 201
    except (ValueError, UnicodeError) as exc:
        db.session.rollback()
        discard_attachments(keys)
        return jsonify(error=str(exc)), 400
    except IntegrityError:
        db.session.rollback()
        discard_attachments(keys)
        return jsonify(error='Source already exists; refresh the list.'), 409
    except Exception:
        db.session.rollback()
        discard_attachments(keys)
        raise


@games_bp.route('/games/<game_uuid>/torrent-sources/<source_id>', methods=['PATCH', 'DELETE'])
@login_required
def torrent_source_edit(game_uuid, source_id):
    if current_user.role != 'admin':
        abort(403)
    acquire_source_mutation_lock(game_uuid) or abort(404)
    source = source_for(game_uuid, source_id)
    data = source_data()
    keys = []
    try:
        if int(data.get('revision', 0)) != source.revision:
            return jsonify(error='Source changed. Refresh before editing.'), 409
    except (ValueError, TypeError):
        return jsonify(error='A valid revision is required.'), 400
    try:
        if request.method == 'DELETE':
            if not source.game.full_disk_path and len(source.game.torrent_sources) == 1 and data.get('delete_game') in (True, '1'):
                from sharewarez.utils.game_core import delete_game
                delete_game(source.game)
                return jsonify(success=True, deleted_game=True, redirect_url=url_for('library.library'))
            if not source.game.full_disk_path and len(source.game.torrent_sources) == 1 and data.get('retain_catalog') not in (True, '1'):
                return jsonify(error='Confirm that this game should remain as a catalog-only entry.'), 400
            db.session.delete(source)
        else:
            label = str(data.get('label', '')).strip()
            if not label or len(label) > 160:
                return jsonify(error='Label must contain 1–160 characters.'), 400
            source.label = label
            if 'magnet' in data or request.files.get('file'):
                values, content = prepare_source(label, data.get('magnet', ''), request.files.get('file'),
                                                 data.get('public') in (True, '1'))
                confirm_hash_variants([(values, content)], data.get('keep_separate') in (True, '1'), source.id, game_uuid)
                from sharewarez.utils.torrent_storage import store_attachment
                if content is not None:
                    values['storage_key'] = store_attachment(content)
                    keys.append(values['storage_key'])
                for name in ('magnet_uri', 'storage_key', 'original_filename', 'info_hash_v1',
                             'info_hash_v2', 'file_sha256', 'file_bytes', 'payload_bytes'):
                    setattr(source, name, None)
                for name, value in values.items():
                    setattr(source, name, value)
        db.session.commit()
        keys = []
        log_system_event(f'Torrent source changed: {source_id} game {game_uuid} actor {current_user.id}', event_type='audit')
        return jsonify(success=True, revision=source.revision)
    except (ValueError, UnicodeError) as exc:
        db.session.rollback()
        discard_attachments(keys)
        return jsonify(error=str(exc)), 400
    except IntegrityError:
        db.session.rollback()
        discard_attachments(keys)
        return jsonify(error='This source already exists on the game.'), 409
    except StaleDataError:
        db.session.rollback()
        discard_attachments(keys)
        return jsonify(error='Source changed. Refresh before editing.'), 409
    except Exception:
        db.session.rollback()
        discard_attachments(keys)
        raise


def record_source_access(source, action):
    db.session.add(TorrentSourceAccess(user_id=current_user.id, user_name=current_user.name,
        game_uuid=source.game_uuid, game_name=source.game.name,
        source_id=source.id, source_label=source.label, action=action,
        file_bytes=source.file_bytes if action == 'torrent_file' else None))
    db.session.commit()


@games_bp.route('/games/<game_uuid>/torrent-sources/<source_id>/magnet', methods=['GET', 'POST'])
@login_required
def torrent_magnet(game_uuid, source_id):
    source = source_for(game_uuid, source_id)
    if source.kind != 'magnet':
        abort(404)
    if request.method == 'POST':
        record_source_access(source, 'magnet_handoff')
    return jsonify(magnet=source.magnet_uri)


@games_bp.route('/games/<game_uuid>/torrent-sources/<source_id>/file')
@login_required
def torrent_file(game_uuid, source_id):
    source = source_for(game_uuid, source_id)
    if source.kind != 'torrent':
        abort(404)
    try:
        data = verified_attachment(source)
    except (FileNotFoundError, ValueError):
        return jsonify(error='Torrent attachment is unavailable. Contact an administrator.'), 404
    response = send_file(BytesIO(data), mimetype='application/x-bittorrent', as_attachment=True,
                     download_name=source.original_filename or 'game.torrent', max_age=0)
    if request.method == 'GET':
        record_source_access(source, 'torrent_file')
    return response
