from pathlib import Path
import pytest

from sharewarez import _sync_changed_theme_files


THEME_SOURCE = Path("sharewarez/setup/default_theme/css/components.css")
REQUESTS_SOURCE = Path("sharewarez/setup/default_theme/css/requests.css")
CACHE_ADMIN_SOURCE = Path("sharewarez/setup/default_theme/css/admin/admin_download_cache.css")


@pytest.fixture
def installed_theme(tmp_path):
    """Exercise installation without depending on ignored local runtime assets."""
    target = tmp_path / 'default'
    _sync_changed_theme_files(Path('sharewarez/setup/default_theme'), target)
    return target


def test_shared_control_contract_is_present_and_synchronized(installed_theme):
    source = THEME_SOURCE.read_text(encoding="utf-8")
    installed = (installed_theme / 'css/components.css').read_text(encoding="utf-8")

    assert source == installed
    assert "--app-control-height: 42px" in source
    assert "--app-control-padding-inline: 12px" in source
    assert "height: var(--app-control-height) !important" in source
    assert "display: inline-flex;" in source
    assert "justify-content: center" in source
    assert "text-align: left" in source
    assert "box-shadow: inset 0 1px 2px rgba(0, 0, 0, .24) !important" in source
    assert "appearance: none !important" in source
    assert "padding-right: 44px !important" in source
    assert "background-position: calc(100% - 26px) 50%" in source
    assert "select:not([multiple]):not([size])" in source


def test_nested_empty_and_table_surfaces_are_flattened():
    css = THEME_SOURCE.read_text(encoding="utf-8")

    assert ".app-surface > :is(" in css
    assert ".favorites-empty-state" in css
    assert ".downloads-empty-state" in css
    assert ".app-surface .table-responsive" in css
    assert "background: transparent !important" in css
    assert "box-shadow: none !important" in css


def test_request_search_shell_owns_its_inner_input_styling(installed_theme):
    source = REQUESTS_SOURCE.read_text(encoding="utf-8")
    installed = (installed_theme / 'css/requests.css').read_text(encoding="utf-8")

    assert source == installed
    assert "#content .requests-page .request-search-wrap input" in source
    assert "height: 100% !important" in source
    assert "min-height: 0 !important" in source
    assert "border: 0 !important" in source
    assert "background: transparent !important" in source
    assert "box-shadow: none !important" in source


def test_download_cache_policy_action_spans_the_form_grid(installed_theme):
    source = CACHE_ADMIN_SOURCE.read_text(encoding="utf-8")
    installed = (installed_theme / 'css/admin/admin_download_cache.css').read_text(encoding="utf-8")

    assert source == installed
    assert ".cache-policy-actions { display:flex;grid-column:1/-1;" in source
    assert ".cache-policy-actions,.cache-policy-actions .btn{width:100%}" in source
    assert ".cache-help" not in source


def test_control_states_and_mobile_card_visibility_are_shared():
    css = THEME_SOURCE.read_text()
    assert '[hidden]:not([hidden="until-found"])' in css
    assert '.btn:not(.btn-circle)' in css
    assert '.btn:not(.btn-lg)' not in css
    assert '.btn[aria-disabled="true"]' in css
    assert 'var(--theme-text-secondary) 50%' in css
    cards = Path('sharewarez/setup/default_theme/css/games/library_browser.css').read_text()
    assert '@media (min-width: 769px) and (hover: hover) and (pointer: fine)' in cards


def test_favorites_uses_library_card_markup_and_interactions():
    template = Path('sharewarez/templates/games/favorites.html').read_text()
    assert "include 'games/library_cards.html'" in template
    assert 'id="gamesContainer"' in template
    assert 'js/game_status_manager.js' in template
    assert 'removeFavoriteModal' not in template
    css = Path('sharewarez/setup/default_theme/css/mobile.css').read_text()
    assert '#content .favorites-page {' not in css
