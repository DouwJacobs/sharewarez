from pathlib import Path


THEME_SOURCE = Path("sharewarez/setup/default_theme/css/components.css")
THEME_INSTALLED = Path("sharewarez/static/library/themes/default/css/components.css")
REQUESTS_SOURCE = Path("sharewarez/setup/default_theme/css/requests.css")
REQUESTS_INSTALLED = Path("sharewarez/static/library/themes/default/css/requests.css")
CACHE_ADMIN_SOURCE = Path("sharewarez/setup/default_theme/css/admin/admin_download_cache.css")
CACHE_ADMIN_INSTALLED = Path("sharewarez/static/library/themes/default/css/admin/admin_download_cache.css")


def test_shared_control_contract_is_present_and_synchronized():
    source = THEME_SOURCE.read_text(encoding="utf-8")
    installed = THEME_INSTALLED.read_text(encoding="utf-8")

    assert source == installed
    assert "--app-control-height: 42px" in source
    assert "--app-control-padding-inline: 12px" in source
    assert "height: var(--app-control-height) !important" in source
    assert "display: inline-flex !important" in source
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


def test_request_search_shell_owns_its_inner_input_styling():
    source = REQUESTS_SOURCE.read_text(encoding="utf-8")
    installed = REQUESTS_INSTALLED.read_text(encoding="utf-8")

    assert source == installed
    assert "#content .requests-page .request-search-wrap input" in source
    assert "height: 100% !important" in source
    assert "min-height: 0 !important" in source
    assert "border: 0 !important" in source
    assert "background: transparent !important" in source
    assert "box-shadow: none !important" in source


def test_download_cache_policy_action_spans_the_form_grid():
    source = CACHE_ADMIN_SOURCE.read_text(encoding="utf-8")
    installed = CACHE_ADMIN_INSTALLED.read_text(encoding="utf-8")

    assert source == installed
    assert ".cache-policy-actions { display:flex;grid-column:1/-1;" in source
    assert ".cache-policy-actions,.cache-policy-actions .btn{width:100%}" in source
    assert ".cache-help" not in source
