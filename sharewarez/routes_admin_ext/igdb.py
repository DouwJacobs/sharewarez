# /sharewarez/routes_admin_ext/igdb.py
from flask import render_template, request, jsonify, redirect, url_for
from flask_login import login_required
from sharewarez.models import GlobalSettings
from sharewarez import db
from sqlalchemy import select
from datetime import datetime, timezone
from . import admin2_bp
from sharewarez.utils.igdb_api import make_igdb_api_request
from sharewarez.utils.auth import admin_required

@admin2_bp.route('/admin/igdb_settings', methods=['GET', 'POST'])
@login_required
@admin_required
def igdb_settings():
    if request.method == 'GET':
        return redirect(url_for('admin2.integrations') + '#igdb', code=308)
    from .settings import save_metadata_credentials
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(status='error', message='Expected a JSON object.'), 400
    # This legacy endpoint accepted incomplete credentials. Preserve that contract,
    # without letting it change provider order, RAWG or unrelated settings.
    normalized = {key: data[key] for key in ('igdb_client_id', 'igdb_client_secret') if key in data}
    return save_metadata_credentials(normalized, credentials_only=True)


@admin2_bp.route('/admin/test_igdb', methods=['POST'])
@login_required
@admin_required
def test_igdb():
    print("Testing IGDB connection...")
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    if not settings or not settings.igdb_client_id or not settings.igdb_client_secret:
        return jsonify({'status': 'error', 'message': 'IGDB settings not configured'}), 400

    try:
        # Test the IGDB API with a simple query
        response = make_igdb_api_request('https://api.igdb.com/v4/games', 'fields name; limit 1;')
        if isinstance(response, list):
            print("IGDB API test successful")
            settings.igdb_last_tested = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({'status': 'success', 'message': 'IGDB API test successful'})
        else:
            print("IGDB API test failed")
            return jsonify({'status': 'error', 'message': 'Invalid API response'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
