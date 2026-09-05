"""Failure recovery must retain the only copy of installed themes."""
from pathlib import Path
from unittest.mock import patch
import os
import pytest
from sharewarez.utils.theme_install import install_packaged_themes


def theme(path, content):
    path.mkdir(parents=True)
    (path / 'theme.json').write_text('{}')
    (path / 'style.css').write_text(content)


def test_failure_restores_existing_bundled_and_default(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    theme(source / 'default_theme', 'new default')
    theme(source / 'bundled_themes' / 'bundled', 'new bundled')
    theme(target / 'default', 'old default')
    theme(target / 'bundled', 'old bundled')
    replace = os.replace
    def fail_publish(src, dst):
        if Path(src).parent.name == 'new' and Path(src).name == 'bundled':
            raise OSError('publication failed')
        return replace(src, dst)
    with patch('sharewarez.utils.theme_install.os.replace', side_effect=fail_publish):
        with pytest.raises(OSError):
            install_packaged_themes(source, target)
    assert (target / 'default' / 'style.css').read_text() == 'old default'
    assert (target / 'bundled' / 'style.css').read_text() == 'old bundled'
    assert not list(target.glob('.theme-install-*'))


def test_failed_rollback_keeps_original_for_manual_recovery(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    theme(source / 'default_theme', 'new')
    theme(target / 'default', 'irreplaceable')
    replace = os.replace
    def fail_publish_and_restore(src, dst):
        if Path(src).parent.name in {'new', 'old'}:
            raise OSError('filesystem failure')
        return replace(src, dst)
    with patch('sharewarez.utils.theme_install.os.replace', side_effect=fail_publish_and_restore):
        with pytest.raises(RuntimeError, match='needs recovery'):
            install_packaged_themes(source, target)
    backups = list(target.glob('.theme-install-*/old/default/style.css'))
    assert len(backups) == 1
    assert backups[0].read_text() == 'irreplaceable'