from datetime import datetime, timezone
from functools import wraps
from flask import request, redirect, url_for, flash
from flask_login import current_user, login_user
from sqlalchemy import func, select
from sharewarez.models import User, db
from sharewarez import login_manager

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def get_safe_next_url():
    """Return a local post-login destination supplied by the request."""
    next_page = (request.form.get('next') or request.args.get('next') or '').strip()
    if (
        not next_page.startswith('/')
        or next_page.startswith('//')
        or '\\' in next_page
        or any(ord(character) < 32 for character in next_page)
    ):
        return None
    return next_page

def _authenticate_and_redirect(username, password):
    user = db.session.execute(select(User).filter(func.lower(User.name) == func.lower(username))).scalars().first()
    
    if user and user.check_password(password):
        user.lastlogin = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=True)
        
        next_page = get_safe_next_url() or url_for('discover.discover')
        return redirect(next_page)
    else:
        flash('Invalid username or password', 'error')
        next_page = get_safe_next_url()
        return redirect(url_for('login.login', next=next_page) if next_page else url_for('login.login'))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("You must be an admin to access this page.", "danger")
            return redirect(url_for('login.login'))
        return f(*args, **kwargs)
    return decorated_function
