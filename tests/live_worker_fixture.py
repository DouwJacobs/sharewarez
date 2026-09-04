"""Real ASGI worker factory used only with an explicitly configured test DB."""
import os
from sqlalchemy.engine import make_url


def make_app():
    url = os.environ['TEST_DATABASE_URL']
    if 'test' not in (make_url(url).database or '').lower():
        raise RuntimeError('Worker fixture requires a test database')
    from sharewarez import create_app
    from asgi import LazyASGIApp
    app = create_app()
    app.config.update(SECRET_KEY='test-secret-key', TESTING=True)
    application = LazyASGIApp()
    application._flask_app = app
    return application
