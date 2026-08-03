from flask import abort, flash, redirect, render_template, url_for
from flask_login import login_required
from sqlalchemy import select

from sharewarez import db
from sharewarez.forms import GameUpdateForm
from sharewarez.models import Game, GameUpdate
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event

from . import games_bp


@games_bp.route('/game/<game_uuid>/updates/<int:update_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def game_update_edit(game_uuid, update_id):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none() or abort(404)
    update = db.session.execute(
        select(GameUpdate).filter_by(id=update_id, game_uuid=game.uuid)
    ).scalar_one_or_none() or abort(404)
    form = GameUpdateForm(obj=update)
    if form.validate_on_submit():
        form.populate_obj(update)
        update.title = (update.title or '').strip() or None
        update.version = (update.version or '').strip() or None
        update.requires_version = (update.requires_version or '').strip() or None
        update.install_instructions = (update.install_instructions or '').strip() or None
        update.changelog = (update.changelog or '').strip() or None
        update.metadata_managed = True
        db.session.commit()
        log_system_event(
            f"Update metadata edited for '{game.name}'",
            event_type='game', event_level='information'
        )
        flash('Update details saved.', 'success')
        return redirect(url_for('games.game_details', game_uuid=game.uuid))
    return render_template('admin/admin_game_update.html', form=form, game=game, update=update)
