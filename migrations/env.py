from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from sharewarez import db
from sharewarez import models  # noqa: F401 - registers model metadata


config = context.config
if config.config_file_name is not None and Path(config.config_file_name).is_file():
    fileConfig(config.config_file_name)
target_metadata = db.metadata


def get_database_url():
    """Resolve the URL for Flask-Migrate and programmatic Alembic callers."""
    configured_url = config.get_main_option('sqlalchemy.url')
    if configured_url:
        return configured_url.replace('%%', '%')
    return db.engine.url.render_as_string(hide_password=False)


def run_migrations_offline():
    context.configure(
        url=get_database_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={'paramstyle': 'named'}, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_engine(get_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
