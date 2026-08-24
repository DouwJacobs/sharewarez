from pathlib import Path


THEME = Path("sharewarez/setup/default_theme")


def test_shared_ui_primitives_cover_feedback_status_and_motion():
    base = (THEME / "css/base.css").read_text(encoding="utf-8")
    components = (THEME / "css/components.css").read_text(encoding="utf-8")

    assert "--status-active-color:" in base
    assert "--status-success-color:" in base
    assert "--status-warning-color:" in base
    assert "--status-danger-color:" in base
    assert ".app-empty-state" in components
    assert ".app-skeleton" in components
    assert ".ui-status" in components
    assert "@media (prefers-reduced-motion: no-preference)" in components
    assert "@keyframes appPageEnter" in components


def test_discover_keeps_secondary_moods_collapsed_and_card_metadata_compact():
    template = (Path("sharewarez/templates/games/discover.html")).read_text(encoding="utf-8")

    assert '<details class="home-quick-discover">' in template
    assert "Quick collection shortcuts" in template
    assert "{{ game.size }}" not in template
    assert "home-game-genres" not in template


def test_library_exposes_sort_before_advanced_filters_and_hides_card_file_size():
    filters = Path("sharewarez/templates/games/library_filters.html").read_text(encoding="utf-8")
    template = Path("sharewarez/templates/games/library_browser.html").read_text(encoding="utf-8")
    javascript = (THEME / "js/library_pagination.js").read_text(encoding="utf-8")

    assert filters.index("library-filter-toolbar") < filters.index("libraryFiltersBody")
    assert filters.index('id="sortSelect"') < filters.index("libraryFiltersBody")
    assert 'aria-busy="false"' in template
    assert "library-game-size" not in template
    assert "library-game-size" not in javascript
    assert "app-skeleton game-card-skeleton-cover" in javascript


def test_play_status_uses_semantic_classes_in_static_and_dynamic_cards():
    library_template = Path("sharewarez/templates/games/library_browser.html").read_text(encoding="utf-8")
    details_template = Path("sharewarez/templates/games/game_details.html").read_text(encoding="utf-8")
    pagination = (THEME / "js/library_pagination.js").read_text(encoding="utf-8")
    manager = (THEME / "js/game_status_manager.js").read_text(encoding="utf-8")
    status_css = (THEME / "css/games/game_status.css").read_text(encoding="utf-8")

    for source in (library_template, details_template, pagination, manager):
        assert "#4A90E2" not in source
        assert "#50C878" not in source
        assert "#FFD700" not in source
    assert "status-icon-unfinished" in library_template
    assert "status-icon-unfinished" in details_template
    assert "status-icon-${currentStatus || 'empty'}" in pagination
    assert "`status-icon-${status || 'empty'}`" in manager
    assert "color: var(--status-success-color)" in status_css


def test_scan_workspace_flattens_active_tab_panel():
    css = (THEME / "css/admin/admin_manage_scanjobs.css").read_text(encoding="utf-8")

    assert ".admin_manage_scanjobs-tab-content > :is(" in css
    assert "backdrop-filter: none;" in css
