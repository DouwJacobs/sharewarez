"""Fresh installs must have the same notification objects as upgraded installs."""

from sqlalchemy import create_engine, text

from sharewarez.utils.migrations import bootstrap_schema_extras


def test_metadata_bootstrap_installs_notification_triggers(app):
    # This module runs in an isolated database in the quality gate. The fixture
    # has created model tables, but intentionally has not run migrations.
    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
    try:
        bootstrap_schema_extras(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE "
                                           "tgname='live_download_change' AND NOT tgisinternal")).scalar_one() == 4
            assert connection.execute(text("SELECT count(*) FROM pg_proc WHERE "
                                           "proname='sharewarez_signal_download_change'")).scalar_one() == 1
    finally:
        engine.dispose()
