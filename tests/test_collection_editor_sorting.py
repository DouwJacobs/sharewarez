from pathlib import Path


def test_collection_editor_supports_drag_ordering_with_button_fallbacks():
    template = Path('sharewarez/templates/admin/admin_collection_editor.html').read_text(encoding='utf-8')
    javascript = Path('sharewarez/setup/default_theme/js/admin_collections.js').read_text(encoding='utf-8')
    css = Path('sharewarez/setup/default_theme/css/admin/admin_collections.css').read_text(encoding='utf-8')

    assert 'Sortable.min.js' not in template
    assert "selectedList.addEventListener('pointerdown'" in javascript
    assert "selectedList.addEventListener('pointermove'" in javascript
    assert "selectedList.addEventListener('pointerup', finishDrag)" in javascript
    assert 'document.elementFromPoint' in javascript
    assert 'dragState.row.cloneNode(true)' in javascript
    assert "dragState.preview.classList.add('collection-sortable-preview')" in javascript
    assert 'dragState.preview?.remove();' in javascript
    assert 'if (orderChanged) sync();' in javascript
    assert "button.matches('[data-move=\"up\"], [data-move-up]')" in javascript
    assert "button.matches('[data-move=\"down\"], [data-move-down]')" in javascript
    assert 'touch-action: none;' in css
    assert 'user-select: none;' in css
    assert '.collection-sortable-preview' in css
    assert 'pointer-events: none;' in css
