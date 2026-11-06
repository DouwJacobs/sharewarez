import re

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import select

from sharewarez import db
from sharewarez.models import Game, GameExtra, GameUpdate
from sharewarez.utils.download_creation import create_or_reuse_download
from sharewarez.utils.event_logging import log_system_event
from . import download_bp


def _validate_uuid(value):
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value, re.IGNORECASE):
        abort(400)


def _initiate(game, content_type='game', record=None):
    form = FlaskForm()
    if request.method == 'POST' and not form.validate_on_submit():
        abort(400)
    try:
        if request.method in {'GET', 'HEAD'}:
            title = game.name if record is None else (getattr(record, 'title', None) or getattr(record, 'name', None) or game.name)
            return render_template('download_confirm.html', form=form, game=game, content_title=title)
        link, created = create_or_reuse_download(current_user.id, game, content_type=content_type, record=record)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('download.downloads'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Download initiation failed for game %s', game.uuid)
        flash('The download could not be prepared. Ask an administrator to check its source and download cache.', 'error')
        return redirect(url_for('download.downloads'))
    log_system_event(f'User {current_user.id} {"created" if created else "reopened"} download request {link.id}', event_type='audit')
    from sharewarez.utils.download_state import download_state
    state = download_state(link)
    if 'download' in state['allowed_actions']:
        return redirect(url_for('download.download_zip', download_id=link.id))
    if state['status'] == 'processing':
        flash('Preparing a resumable download. You can leave this page and return later.', 'info')
    else:
        flash(state['message'] or 'Manage this link from Downloads.', 'info')
    return redirect(url_for('download.downloads'))


@download_bp.route('/download_game/<game_uuid>', methods=['GET', 'POST'])
@login_required
def download_game(game_uuid):
    _validate_uuid(game_uuid)
    game = db.session.scalar(select(Game).where(Game.uuid == game_uuid)) or abort(404)
    return _initiate(game)


@download_bp.route('/download_other/<file_type>/<game_uuid>/<file_id>', methods=['GET', 'POST'])
@login_required
def download_other(file_type, game_uuid, file_id):
    _validate_uuid(game_uuid)
    if file_type not in {'update', 'extra'}:
        flash('Invalid file type.', 'error')
        return redirect(url_for('games.game_details', game_uuid=game_uuid))
    try:
        file_id = int(file_id)
    except ValueError:
        abort(400)
    model = GameUpdate if file_type == 'update' else GameExtra
    record = db.session.scalar(select(model).where(model.id == file_id, model.game_uuid == game_uuid))
    if record is None:
        flash(f'{file_type.capitalize()} file not found.', 'error')
        return redirect(url_for('games.game_details', game_uuid=game_uuid))
    game = db.session.scalar(select(Game).where(Game.uuid == game_uuid)) or abort(404)
    return _initiate(game, file_type, record)