from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_library_hover_preview_uses_modern_accessible_structure():
    template = (ROOT / "sharewarez/templates/games/library_browser.html").read_text(encoding="utf-8")
    script = (ROOT / "sharewarez/setup/default_theme/js/library_slideshow.js").read_text(encoding="utf-8")
    css = (ROOT / "sharewarez/setup/default_theme/css/games/library_browser.css").read_text(encoding="utf-8")

    assert 'data-uuid="{{ game.uuid }}"' in template
    assert 'aria-hidden="true"' in template
    assert "hoverPreviewMedia.matches" in script
    assert "escapeHtml(element.dataset.name" in script
    assert "library-hover-preview-media" in script
    assert "library-hover-preview-placeholder" in script
    assert ".game-card-container.preview-open" in css
    assert "width: min(360px, calc(100vw - 32px));" in css
    assert "@media (hover: none), (pointer: coarse), (max-width: 768px)" in css
