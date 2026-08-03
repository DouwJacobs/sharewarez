from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment


def _render_file_row(file_data, file_type):
    source = Path('sharewarez/templates/games/game_details.html').read_text(encoding='utf-8')
    macro_start = source.index('{% macro get_file_icon')
    macro_end = source.index('{% macro list_items')
    macros = source[macro_start:macro_end]
    template = Environment(autoescape=True).from_string(
        macros + "{{ render_file_row(file_data, 'game-uuid', file_type) }}"
    )
    template.globals['url_for'] = lambda endpoint, **values: '/download'
    return template.render(
        file_data=file_data,
        file_type=file_type,
        current_user=SimpleNamespace(role='user'),
    )


def test_structured_update_uses_display_name_without_file_path():
    rendered = _render_file_row({
        'id': 1,
        'display_name': 'Update 1.0.4',
        'file_size': '1 GB',
        'update_number': 1,
    }, 'update')

    assert 'Update 1.0.4' in rendered
    assert 'Download' in rendered
    assert 'fa-download' in rendered


def test_legacy_extra_falls_back_to_path_basename():
    rendered = _render_file_row({
        'id': 2,
        'file_path': '/storage/Game/extras/Soundtrack.zip',
        'file_size': '100 MB',
    }, 'extra')

    assert 'Soundtrack.zip' in rendered
