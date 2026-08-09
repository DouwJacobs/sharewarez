from pathlib import Path


def test_mobile_navigation_is_accessible_and_theme_aware():
    template = Path('sharewarez/templates/base.html').read_text()
    css = Path('sharewarez/setup/default_theme/css/mobile.css').read_text()

    assert 'class="mobile-bottom-nav" aria-label="Primary navigation"' in template
    assert template.count('aria-current="page"') >= 5
    assert 'env(safe-area-inset-bottom)' in css
    assert '--theme-sidebar-top' in css
    assert '.mobile-bottom-nav a.active' in css
    assert '@media (min-width: 769px)' in css
