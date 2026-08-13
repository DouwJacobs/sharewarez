from pathlib import Path

from sharewarez.init_manager import InitializationManager


def _write_theme(root: Path, name: str, content: str) -> None:
    theme = root / name
    theme.mkdir(parents=True, exist_ok=True)
    (theme / "theme.json").write_text('{}', encoding="utf-8")
    (theme / "asset.css").write_text(content, encoding="utf-8")


def test_packaged_themes_refresh_without_dev_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup = tmp_path / "sharewarez" / "setup"
    installed = tmp_path / "sharewarez" / "static" / "library" / "themes"
    _write_theme(setup, "default_theme", "new default")
    _write_theme(setup / "bundled_themes", "midnight", "new midnight")
    _write_theme(installed, "default", "old default")
    _write_theme(installed, "midnight", "old midnight")
    _write_theme(installed, "custom", "keep custom")

    manager = InitializationManager()
    manager._setup_default_theme(str(installed), dev_mode=False)
    manager._setup_bundled_themes(str(installed), dev_mode=False)

    assert (installed / "default" / "asset.css").read_text() == "new default"
    assert (installed / "midnight" / "asset.css").read_text() == "new midnight"
    assert (installed / "custom" / "asset.css").read_text() == "keep custom"
