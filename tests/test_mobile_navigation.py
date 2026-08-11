from pathlib import Path


def test_mobile_navigation_is_accessible_and_theme_aware():
    template = Path('sharewarez/templates/base.html').read_text()
    css = Path('sharewarez/setup/default_theme/css/mobile.css').read_text()

    assert 'class="mobile-bottom-nav" aria-label="Primary navigation"' in template
    assert template.count('aria-current="page"') >= 5
    assert 'env(safe-area-inset-bottom)' in css
    assert '--theme-sidebar-top' in css
    assert '.mobile-bottom-nav > a.active' in css
    assert 'class="mobile-more"' in template
    assert 'Administration' in template
    assert '#sidebarBackdrop' in css and 'display: none !important' in css
    assert '@media (min-width: 769px)' in css


def test_mobile_navigation_order_has_admin_controls():
    template = Path('sharewarez/templates/admin/new_server_settings.html').read_text()
    javascript = Path('sharewarez/setup/default_theme/js/admin_manage_server_settings.js').read_text()

    assert template.count('class="form-select form-select-sm mobile-nav-slot"') == 1
    assert "mobileNavOrder:" in javascript
    assert "new Set(settings.mobileNavOrder)" in javascript


def test_mobile_pages_use_one_shared_outer_gutter():
    css = Path('sharewarez/setup/default_theme/css/mobile.css').read_text()

    assert 'CANONICAL MOBILE PAGE GUTTER' in css
    assert '--mobile-page-gutter: 12px' in css
    assert '.admin_manage_libraries-library-container' in css
    assert '.container-settings-dashboard > .container' in css
    assert '#content .favorites-page' in css
    assert 'margin-right: 0 !important' in css
    assert 'margin-left: 0 !important' in css


def test_featured_carousel_supports_directional_touch_swipes():
    javascript = Path('sharewarez/setup/default_theme/js/games/discover.js').read_text()
    css = Path('sharewarez/setup/default_theme/css/games/discover.css').read_text()

    assert "carousel.addEventListener('touchstart'" in javascript
    assert "carousel.addEventListener('touchend'" in javascript
    assert 'Math.abs(deltaX) >= 48' in javascript
    assert 'touch-action: pan-y' in css


def test_primary_routes_use_shared_page_layout_primitives():
    components = Path('sharewarez/setup/default_theme/css/components.css').read_text()
    templates = [
        Path('sharewarez/templates/games/discover.html'),
        Path('sharewarez/templates/games/library_browser.html'),
        Path('sharewarez/templates/games/favorites.html'),
        Path('sharewarez/templates/games/manage_downloads.html'),
        Path('sharewarez/templates/requests/requests.html'),
        Path('sharewarez/templates/admin/admin_dashboard.html'),
        Path('sharewarez/templates/admin/admin_manage_users.html'),
        Path('sharewarez/templates/admin/admin_manage_libraries.html'),
    ]

    for primitive in ('.app-page', '.app-page-header', '.app-surface', '.app-stack'):
        assert primitive in components
    for template in templates:
        assert 'app-page' in template.read_text(), template


def test_user_surfaces_follow_the_unified_card_structure():
    requests = Path('sharewarez/templates/requests/requests.html').read_text()
    downloads = Path('sharewarez/templates/games/manage_downloads.html').read_text()
    favorites_css = Path('sharewarez/setup/default_theme/css/games/favorites.css').read_text()

    assert 'Community wishlist' not in requests
    assert 'request-main-card' in requests
    assert requests.index('requestSearchForm') < requests.index('My requests')
    assert downloads.index('downloads-panel') < downloads.index("page_header('My downloads'")
    assert '.favorites-empty-state' in favorites_css
    assert 'background: transparent' in favorites_css


def test_help_accordion_is_scoped_keyboard_accessible_and_theme_aware():
    template = Path('sharewarez/templates/site/site_help.html').read_text()
    css = Path('sharewarez/setup/default_theme/css/site/help.css').read_text()

    assert "querySelectorAll('.help-card > .card-header')" in template
    assert "event.key === 'Enter' || event.key === ' '" in template
    assert 'Auto-expand all cards' not in template
    assert '.help-card > .card-header' in css
    assert 'var(--theme-card-background' in css
    assert '.help-card kbd' in css
    assert 'grid-template-columns: minmax(0, 1fr)' in css
    assert '.help-card { align-self: start; }' in css


def test_shared_page_header_only_uses_flex_for_standard_actions():
    css = Path('sharewarez/setup/default_theme/css/components.css').read_text()
    dashboard = Path('sharewarez/templates/admin/admin_dashboard.html').read_text()

    assert '.app-page-header:has(> .app-page-actions)' in css
    header = dashboard.split('<header class="app-page-header admin-dashboard-header">', 1)[1]
    assert header.lstrip().startswith('<div>')
