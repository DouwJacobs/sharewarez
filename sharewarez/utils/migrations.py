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


def stamp_database(database_uri, revision='head'):
    """Record the revision represented by an already-current schema."""
    command.stamp(alembic_config(database_uri), revision)


def bootstrap_schema_extras(engine):
    """Install non-model DDL on a fresh metadata-created schema before stamping.

    Keep this registry explicit: historical column/table migrations must NOT run
    after create_all. These immutable revisions contain only non-model objects.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(alembic_config('postgresql://unused/unused'))
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            scripts.get_revision('20260904_24').module.upgrade()
            scripts.get_revision('20260905_25').module.upgrade()


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


def head_revision():
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config('postgresql://unused/unused')).get_current_head()


def database_needs_upgrade(database_uri):
    return current_revision(database_uri) != head_revision()
