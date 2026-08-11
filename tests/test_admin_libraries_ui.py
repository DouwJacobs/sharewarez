from pathlib import Path


def test_library_table_uses_theme_aware_table_and_action_controls():
    template = Path('sharewarez/templates/admin/admin_manage_libraries.html').read_text(encoding='utf-8')
    css = Path('sharewarez/setup/default_theme/css/admin/admin_manage_libraries.css').read_text(encoding='utf-8')

    assert 'class="library-actions-toggle"' in template
    assert 'library-actions-menu' in template
    assert 'dropdown-menu-dark' not in template
    assert 'library-drag-cell' in template
    assert 'style="cursor: move;"' not in template
    assert '.libraries-table-wrapper .table :is(th, td)' in css
    assert 'border-collapse: separate !important;' in css
    assert 'border-top-left-radius: 13px;' in css
    assert 'border-top-right-radius: 13px;' in css
    assert 'border-bottom-left-radius: 13px;' in css
    assert 'border-bottom-right-radius: 13px;' in css
    assert 'rgba(var(--theme-accent-soft-rgb' in css
    assert '.library-actions-menu .dropdown-item' in css
