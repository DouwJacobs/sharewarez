from pathlib import Path


def test_fresh_schema_is_stamped_at_current_migration_head():
    script = Path('scripts/quality-gate.sh').read_text(encoding='utf-8')

    assert 'db stamp head' in script
    assert 'db stamp 20260809_01' not in script
    assert script.index('db.create_all()') < script.index('db stamp head')
    assert script.count('CREATE EXTENSION IF NOT EXISTS pg_trgm') == 2
