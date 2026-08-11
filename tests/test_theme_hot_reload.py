from pathlib import Path

from sharewarez import _sync_changed_theme_files


def test_theme_sync_does_not_rewrite_unchanged_files(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    (source / 'css').mkdir()
    source_file = source / 'css' / 'theme.css'
    source_file.write_text('body { color: red; }', encoding='utf-8')

    assert _sync_changed_theme_files(source, target) == 1
    target_file = target / 'css' / 'theme.css'
    first_mtime = target_file.stat().st_mtime_ns

    assert _sync_changed_theme_files(source, target) == 0
    assert target_file.stat().st_mtime_ns == first_mtime


def test_theme_sync_copies_changed_and_new_files(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()
    (source / 'theme.js').write_text('first', encoding='utf-8')
    (target / 'theme.js').write_text('old', encoding='utf-8')
    (source / 'new.js').write_text('new', encoding='utf-8')

    assert _sync_changed_theme_files(source, target) == 2
    assert (target / 'theme.js').read_text(encoding='utf-8') == 'first'
    assert (target / 'new.js').read_text(encoding='utf-8') == 'new'
