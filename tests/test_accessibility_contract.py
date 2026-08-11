from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "sharewarez" / "templates"
THEME = ROOT / "sharewarez" / "setup" / "default_theme"


def test_custom_dialogs_have_accessible_names_and_focus_management():
    sources = [
        TEMPLATES / "partials" / "delete_game_modal.html",
        TEMPLATES / "games" / "favorites.html",
        TEMPLATES / "games" / "game_details.html",
    ]

    for source in sources:
        markup = source.read_text(encoding="utf-8")
        for fragment in markup.split('data-focus-managed-dialog')[:-1]:
            opening_tag = fragment.rsplit("<", 1)[-1]
            assert 'role="dialog"' in opening_tag, source
            assert 'aria-modal="true"' in opening_tag, source
            assert ('aria-labelledby="' in opening_tag or 'aria-label="' in opening_tag), source
            assert 'aria-hidden="true"' in opening_tag, source


def test_focus_manager_traps_focus_closes_and_restores_trigger():
    script = (THEME / "js" / "modal_manager.js").read_text(encoding="utf-8")

    assert "event.key !== 'Tab'" in script
    assert "event.key === 'Escape'" in script
    assert "returnFocus.set" in script
    assert "target.focus({preventScroll: true})" in script
    assert "[data-dialog-close]" in script
    assert "show.bs.modal" in script
    assert "hidden.bs.modal" in script
    assert "bootstrapReturnFocus.set" in script


def test_custom_dialog_close_controls_are_buttons():
    for source in TEMPLATES.rglob("*.html"):
        markup = source.read_text(encoding="utf-8")
        for fragment in markup.split("data-dialog-close")[:-1]:
            opening_tag = fragment.rsplit("<", 1)[-1]
            assert opening_tag.lstrip().startswith("button"), source
            assert 'aria-label="Close"' in opening_tag, source


def test_game_details_does_not_redeclare_base_modal_block_inside_content():
    markup = (TEMPLATES / "games" / "game_details.html").read_text(encoding="utf-8")

    assert "{% block modals %}" not in markup
