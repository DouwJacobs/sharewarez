from pathlib import Path


def test_fresh_database_is_stamped_before_historical_migrations_run():
    source = Path('sharewarez/init_manager.py').read_text(encoding='utf-8')

    fresh_database_branch = source.index('if not has_existing_data_schema:')
    legacy_database_branch = source.index('elif not is_versioned or not has_application_schema:')
    stamp_call = source.index('stamp_database(Config.SQLALCHEMY_DATABASE_URI)')

    assert fresh_database_branch < stamp_call < legacy_database_branch
