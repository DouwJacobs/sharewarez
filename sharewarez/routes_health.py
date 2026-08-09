from flask import Blueprint, jsonify
from sqlalchemy import text

from sharewarez import db
from sharewarez.version import __version__


health_bp = Blueprint('health', __name__)


@health_bp.get('/health/live')
def live():
    return jsonify(status='ok', version=__version__)


@health_bp.get('/health/ready')
def ready():
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        db.session.rollback()
        return jsonify(status='unavailable'), 503
    return jsonify(status='ready', version=__version__)
