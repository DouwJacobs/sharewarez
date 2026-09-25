from flask import flash, jsonify, redirect, render_template, url_for
from flask_login import login_required

from sharewarez.utils.event_logging import log_system_event

from . import download_bp

@download_bp.route('/play_game/<game_uuid>', methods=['GET'])
@login_required
def play_game(game_uuid):
    """Placeholder route for the play game functionality"""
    flash("Play game functionality coming soon!", "info")
    return redirect(url_for('games.game_details', game_uuid=game_uuid))

@download_bp.route('/playromtest', methods=['GET'])
@login_required
def playromtest():
    """Placeholder route for the play game functionality"""
    flash("Play game functionality coming soon!", "info")
    return render_template('games/playrom.html')

# NOTE: This API route is now handled by ASGI for async streaming  
# This Flask route should not be reached as ASGI intercepts it first
@download_bp.route('/api/downloadrom/<string:guid>', methods=['GET'])
@login_required
def downloadrom(guid):
    """
    ROM download route - now handled by ASGI for async streaming.
    This Flask route should not be reached.
    """
    # This route should not be reached as ASGI intercepts download routes
    log_system_event(f"Flask ROM download route reached unexpectedly for UUID: {guid}", 
                    event_type='system', event_level='warning')
    return jsonify({"error": "ROM download route should be handled by ASGI"}), 500
