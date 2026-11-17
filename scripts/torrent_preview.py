"""Disposable local preview for torrent source browser acceptance checks."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if 'torrent_preview' not in os.environ.get('DATABASE_URL', ''):
    raise RuntimeError('Use an isolated torrent_preview database.')
os.environ['SHAREWAREZ_INITIALIZATION_COMPLETE'] = 'true'
from flask import redirect
from flask_login import login_user
from sharewarez import create_app, db
from sharewarez.models import User, Library, GlobalSettings
from sharewarez.platform import LibraryPlatform

app = create_app()
app.config.update(TESTING=True, WTF_CSRF_ENABLED=True, TORRENT_STORAGE_DIR='/tmp/gamelibrary-torrent-preview-files')
app.jinja_env.auto_reload = True
with app.app_context():
    db.create_all()
    if not db.session.query(User).filter_by(name='torrent_preview_admin').first():
        db.session.add_all([
            User(name='torrent_preview_admin', email='admin@preview.test', role='admin', password_hash='unused', is_email_verified=True),
            User(name='torrent_preview_member', email='member@preview.test', role='user', password_hash='unused', is_email_verified=True),
            Library(name='Torrent preview library', platform=LibraryPlatform.PCWIN),
            GlobalSettings(setup_completed=True),
        ])
        db.session.commit()


@app.get('/_torrent_preview/session/<role>')
def preview_session(role):
    if role not in ('admin', 'member'):
        return 'Unknown role', 404
    user = db.session.query(User).filter_by(name='torrent_preview_' + role).one()
    login_user(user)
    return redirect('/library')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5017, use_reloader=False)
