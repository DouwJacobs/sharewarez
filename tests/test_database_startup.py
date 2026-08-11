from pathlib import Path


def test_application_readiness_check_uses_configured_database_port():
    source = Path('sharewarez/__init__.py').read_text(encoding='utf-8')

    assert 'parsed_url.port or 5432' in source
    assert 'check_postgres_port_open(parsed_url.hostname, 5432' not in source
