"""Fresh global availability checks for completion-time enrichment."""
from sqlalchemy import select
from sharewarez import db
from sharewarez.models import GlobalSettings


def hltb_allowed():
    # Read the authoritative column, bypassing cached settings and loaded objects.
    return bool(db.session.scalar(select(GlobalSettings.enable_hltb_integration).order_by(GlobalSettings.id).limit(1)))


def enrich_manual_candidate(game, selection):
    if not selection or not selection.get('options', {}).get('fetch_hltb') or not hltb_allowed():
        return
    from sharewarez.utils.hltb import update_game_hltb_sync
    try:
        update_game_hltb_sync(game.uuid, game.name)
    except Exception:
        from flask import current_app
        current_app.logger.warning('Completion-time enrichment failed for game %s', game.uuid)
