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
