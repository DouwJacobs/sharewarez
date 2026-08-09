# /sharewarez/routes_apis/library.py
from flask import jsonify, request, url_for
from flask_login import current_user, login_required
from sharewarez import db
from sharewarez.models import Collection, Library
from sharewarez.utils.auth import admin_required
from sqlalchemy import select
from sharewarez.utils.collections import collection_visibility_clause
from . import apis_bp

@apis_bp.route('/get_libraries')
@login_required
def get_libraries():
    # Direct query to the Library model, ordered alphabetically by name
    libraries_query = db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all()
    libraries = [
        {
            'uuid': lib.uuid,
            'name': lib.name,
            'image_url': lib.image_url if lib.image_url else url_for('static', filename='newstyle/default_library.jpg')
        } for lib in libraries_query
    ]
    print(f"Returning {len(libraries)} libraries.")
    return jsonify(libraries)


@apis_bp.route('/collections')
@login_required
def get_collections():
    collections = db.session.execute(
        select(Collection)
        .where(Collection.game_links.any(), collection_visibility_clause(current_user))
        .order_by(Collection.is_featured.desc(), Collection.name)
    ).scalars().all()
    return jsonify([{'slug': item.slug, 'name': item.name} for item in collections])

@apis_bp.route('/reorder_libraries', methods=['POST'])
@login_required
@admin_required
def reorder_libraries():
    try:
        new_order = request.json.get('order', [])
        for index, library_uuid in enumerate(new_order):
            library = db.session.get(Library, library_uuid)
            if library:
                library.display_order = index
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@apis_bp.route('/library/<string:library_uuid>', methods=['GET'])
@login_required
def get_library(library_uuid):
    """Return information about a specific library"""
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if not library:
        return jsonify({'error': 'Library not found'}), 404
        
    return jsonify({
        'uuid': library.uuid,
        'name': library.name,
        'platform': library.platform.name
    })
