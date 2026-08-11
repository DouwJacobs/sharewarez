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


def test_library_cards_follow_the_cover_height_at_fluid_grid_widths():
    css = (ROOT / "sharewarez/setup/default_theme/css/games/library_browser.css").read_text(encoding="utf-8")

    card_rule = css.split(".game-library-container .game-card {", 1)[1].split("}", 1)[0]
    link_rule = css.split(".game-library-container .game-card > a {", 1)[1].split("}", 1)[0]

    assert "min-height: 0;" in card_rule
    assert "background: transparent !important;" in card_rule
    assert "border: 0 !important;" in card_rule
    assert "display: block;" in link_rule
