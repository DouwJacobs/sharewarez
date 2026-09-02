from pathlib import Path


THEME_SOURCE = Path("sharewarez/setup/default_theme/css/components.css")
THEME_INSTALLED = Path("sharewarez/static/library/themes/default/css/components.css")


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
    assert "appearance: auto !important" in source
    assert "background-image: none !important" in source


def test_nested_empty_and_table_surfaces_are_flattened():
    css = THEME_SOURCE.read_text(encoding="utf-8")

    assert ".app-surface > :is(" in css
    assert ".favorites-empty-state" in css
    assert ".downloads-empty-state" in css
    assert ".app-surface .table-responsive" in css
    assert "background: transparent !important" in css
    assert "box-shadow: none !important" in css
