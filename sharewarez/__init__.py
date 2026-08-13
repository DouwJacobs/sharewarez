#/sharewarez/__init__.py
import sys, os
import filecmp
import shutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask_mail import Mail
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from config import Config
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from flask_caching import Cache
from sharewarez.utils.db import check_postgres_port_open
from sharewarez.version import __version__
from sharewarez.security import init_http_security
from sharewarez.observability import init_observability

db = SQLAlchemy()
migrate = Migrate(compare_type=True)
login_manager = LoginManager()
mail = Mail()
cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})
app_start_time = datetime.now()
# Backwards-compatible template/API name. VERSION is the authoritative source.
app_version = __version__


def _sync_changed_theme_files(source, target):
    """Copy only changed theme files so the reload watcher settles after one pass."""
    copied = 0
    for source_root, _directories, filenames in os.walk(source):
        relative_root = os.path.relpath(source_root, source)
        target_root = target if relative_root == '.' else os.path.join(target, relative_root)
        os.makedirs(target_root, exist_ok=True)
        for filename in filenames:
            source_path = os.path.join(source_root, filename)
            target_path = os.path.join(target_root, filename)
            if os.path.isfile(target_path) and filecmp.cmp(
                source_path, target_path, shallow=False
            ):
                continue
            shutil.copy2(source_path, target_path)
            copied += 1
    return copied


def create_app():
    # The default theme is authored under setup/default_theme but served from
    # static/library/themes/default. Refresh it whenever Uvicorn recreates the
    # development app so CSS/JS edits participate in hot reload as expected.
    if os.getenv('SHAREWAREZ_HOT_RELOAD', 'false').lower() == 'true':
        default_theme_source = os.path.join(
            os.path.dirname(__file__), 'setup', 'default_theme'
        )
        default_theme_target = os.path.join(
            os.path.dirname(__file__), 'static', 'library', 'themes', 'default'
        )
        if os.path.isdir(default_theme_source):
            os.makedirs(os.path.dirname(default_theme_target), exist_ok=True)
            _sync_changed_theme_files(default_theme_source, default_theme_target)

    app = Flask(__name__)
    app.config.from_object(Config)

    # SAFETY CHECK: Prevent production database access during tests
    import sys
    if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
        # We are running in pytest - ensure we're using test database
        test_db_url = os.getenv('TEST_DATABASE_URL')
        production_db_url = os.getenv('DATABASE_URL')

        # If DATABASE_URL was not properly overridden in conftest.py
        if production_db_url and test_db_url and production_db_url != test_db_url:
            if 'sharewarez' in production_db_url and 'test' not in production_db_url:
                print(f"🚨 CRITICAL: Tests attempting to use production database: {production_db_url}")
                print(f"🛡️  BLOCKING: Forcing test database: {test_db_url}")
                app.config['SQLALCHEMY_DATABASE_URI'] = test_db_url

        print(f"🧪 PYTEST MODE: Using database: {app.config.get('SQLALCHEMY_DATABASE_URI', 'NOT SET')}")

    CSRFProtect(app)
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/library')

    # --- BEGIN: Print masked PostgreSQL connection string ---
    raw_db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    parsed_uri = urlparse(raw_db_uri)
    if parsed_uri.password:
        # Create a new netloc with the masked password
        netloc_parts = parsed_uri.netloc.split('@')
        auth_part = netloc_parts[0].replace(parsed_uri.password, '********')
        masked_netloc = f"{auth_part}@{netloc_parts[1]}" if len(netloc_parts) > 1 else auth_part
        masked_uri = urlunparse(parsed_uri._replace(netloc=masked_netloc))
        print(f"Attempting to connect to PostgreSQL with URI: {masked_uri}")
    else:
        print(f"Attempting to connect to PostgreSQL with URI: {raw_db_uri}")
    # --- END: Print masked PostgreSQL connection string ---

    parsed_url = urlparse(app.config['SQLALCHEMY_DATABASE_URI'])
    check_postgres_port_open(parsed_url.hostname, parsed_url.port or 5432, 60, 2)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    login_manager.login_view = 'login.login'
    cache.init_app(app)
    init_observability(app)
    init_http_security(app)

    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle file upload size limit exceeded errors."""
        from flask import flash, redirect, request
        flash('The file you tried to upload is too large. Maximum file size is 10MB.', 'error')
        return redirect(request.url)

    @app.context_processor
    def inject_current_theme():
        """Inject the active theme and instance branding into every template."""
        from sharewarez.utils.processors import get_global_settings
        from sharewarez.utils.pwa import get_pwa_branding

        from sharewarez.utils.themes import resolve_theme_id
        current_theme = resolve_theme_id(current_user, app)
        pwa_branding = get_pwa_branding()
        unread_notification_count = 0
        if current_user.is_authenticated:
            from sqlalchemy import func, select
            from sharewarez.models import Notification
            unread_notification_count = db.session.execute(
                select(func.count(Notification.id)).where(
                    Notification.user_id == current_user.id,
                    Notification.read_at.is_(None),
                )
            ).scalar_one()
        return dict(
            current_theme=current_theme,
            pwa_theme_color=pwa_branding['theme_color'],
            pwa_revision=pwa_branding['revision'],
            unread_notification_count=unread_notification_count,
            **get_global_settings(),
        )

    @app.before_request
    def check_setup_status():
        """Check if setup is required and redirect accordingly."""
        from flask import request, redirect
        from sharewarez.utils.setup import should_redirect_to_setup, get_setup_redirect_url

        # Route tests exercise authentication and setup independently. Avoid
        # letting an empty isolated test database mask the behavior under test.
        if app.config.get('TESTING'):
            return

        # Skip setup checks for certain endpoints
        exempt_endpoints = {
            'setup.setup', 'setup.setup_submit', 'setup.setup_smtp', 'setup.setup_igdb',
            'static', 'favicon', 'site.favicon', 'site.pwa_manifest', 'site.pwa_icon',
            'site.service_worker', 'site.pwa_offline', 'health.live', 'health.ready'
        }

        # Skip setup checks for API endpoints (they should handle their own authentication)
        if request.endpoint and (
            request.endpoint in exempt_endpoints or
            request.endpoint.startswith('apis.') or
            request.path.startswith('/api/')
        ):
            return

        # Check if we need to redirect to setup
        if should_redirect_to_setup():
            setup_url = get_setup_redirect_url()
            if request.endpoint and request.path != setup_url:
                return redirect(setup_url)

    # Import models and routes
    from . import routes, models
    from sharewarez.routes_site import site_bp
    from sharewarez.routes_library import library_bp
    from sharewarez.routes_setup import setup_bp
    from sharewarez.routes_settings import settings_bp
    from sharewarez.routes_login import login_bp
    from sharewarez.routes_discover import discover_bp
    from sharewarez.routes_downloads_ext import download_bp
    from sharewarez.routes_games_ext import games_bp
    from sharewarez.routes_smtp import smtp_bp
    from sharewarez.routes_info import info_bp
    from sharewarez.routes_admin_ext import admin2_bp
    from sharewarez.routes_apis import apis_bp
    from sharewarez.routes_game_requests import game_requests_bp
    from sharewarez.routes_health import health_bp
    from sharewarez.routes_notifications import notifications_bp

    # Register all blueprints
    app.register_blueprint(routes.bp)
    app.register_blueprint(site_bp)
    app.register_blueprint(admin2_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(login_bp)
    app.register_blueprint(discover_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(smtp_bp)
    app.register_blueprint(info_bp)
    app.register_blueprint(apis_bp)
    app.register_blueprint(game_requests_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(notifications_bp)

    with app.app_context():
        # Database initialization is handled by the InitializationManager before workers start
        # Worker processes skip initialization entirely since it's already done
        if ('pytest' not in sys.modules and 'PYTEST_CURRENT_TEST' not in os.environ and
            os.getenv('SHAREWAREZ_INITIALIZATION_COMPLETE') != 'true'):
            # This should only happen in development or if initialization wasn't run
            print("⚠️  Initialization not completed - this may cause issues")

    return app
