import os

from sharewarez.environment import (
    get_product_env,
    product_env_enabled,
    set_product_env,
)


def test_current_product_prefix_takes_precedence(monkeypatch):
    monkeypatch.setenv('GAMELIBRARY_HOT_RELOAD', 'false')
    monkeypatch.setenv('SHAREWAREZ_HOT_RELOAD', 'true')

    assert get_product_env('HOT_RELOAD') == 'false'
    assert product_env_enabled('HOT_RELOAD') is False


def test_legacy_product_prefix_remains_supported(monkeypatch):
    monkeypatch.delenv('GAMELIBRARY_INITIALIZATION_COMPLETE', raising=False)
    monkeypatch.setenv('SHAREWAREZ_INITIALIZATION_COMPLETE', 'true')

    assert product_env_enabled('INITIALIZATION_COMPLETE') is True


def test_product_environment_default(monkeypatch):
    monkeypatch.delenv('GAMELIBRARY_HOT_RELOAD', raising=False)
    monkeypatch.delenv('SHAREWAREZ_HOT_RELOAD', raising=False)

    assert get_product_env('HOT_RELOAD', 'disabled') == 'disabled'
    assert product_env_enabled('HOT_RELOAD') is False


def test_setting_product_environment_updates_both_names(monkeypatch):
    monkeypatch.delenv('GAMELIBRARY_MIGRATIONS_COMPLETE', raising=False)
    monkeypatch.delenv('SHAREWAREZ_MIGRATIONS_COMPLETE', raising=False)

    set_product_env('MIGRATIONS_COMPLETE', 'true')

    assert os.environ['GAMELIBRARY_MIGRATIONS_COMPLETE'] == 'true'
    assert os.environ['SHAREWAREZ_MIGRATIONS_COMPLETE'] == 'true'
