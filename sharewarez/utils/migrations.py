"""Programmatic Alembic integration used before web workers start."""

from pathlib import Path

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = PROJECT_ROOT / 'migrations'


def alembic_config(database_uri):
    config = Config(str(PROJECT_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(MIGRATIONS_DIR))
    # ConfigParser treats percent signs in escaped credentials as interpolation.
    config.set_main_option('sqlalchemy.url', database_uri.replace('%', '%%'))
    return config


def upgrade_database(database_uri, revision='head'):
    """Upgrade the configured database and fail startup on migration errors."""
    command.upgrade(alembic_config(database_uri), revision)


def current_revision(database_uri):
    """Return the database revision, or None before the baseline is applied."""
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(database_uri)
    try:
        if 'alembic_version' not in inspect(engine).get_table_names():
            return None
        with engine.connect() as connection:
            return connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
    finally:
        engine.dispose()
