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


def test_game_details_uses_storefront_product_structure():
    template = Path('sharewarez/templates/games/game_details.html').read_text(encoding='utf-8')
    css = Path('sharewarez/setup/default_theme/css/games/game_details.css').read_text(encoding='utf-8')

    assert 'app-page app-page--wide game-details-page' in template
    assert 'glass-panel-gamecard game-storefront' in template
    assert 'storefront_art' not in template
    assert 'game-storefront-time-to-beat' in template
    assert 'game-storefront-time-values' in template
    assert 'game-storefront-time-refresh' in template
    assert 'game-card-topq{% if game.hltb_main_story' in template
    assert 'game-storefront-heading' in template
    assert 'game-storefront-acquisition' in template
    assert 'game-relationships' in template
    assert 'game.relationship_groups' in template
    assert 'related.game_uuid' in template
    assert '<button type="submit" class="button-glass-download"' in template
    assert '.game-storefront::before' in css
    assert 'display: none !important;' in css
    assert '.game-storefront-time-to-beat' in css
    assert '.game-storefront-time-refresh' in css
    assert '.game-card-topq.has-time-to-beat' in css
    assert '.game-storefront .game-card-topq' in css
    assert '.game-storefront .game-card-downloads' in css
    assert 'background: transparent !important;' in css
    assert 'overflow: visible;' in css
    assert '.game-storefront .rating-row + .rating-row' in css
    assert '.game-relationship-row' in css


def test_game_details_mobile_storefront_uses_shared_outer_gutter():
    css = Path('sharewarez/setup/default_theme/css/games/game_details.css').read_text(encoding='utf-8')
    storefront_mobile = css.rsplit('@media (max-width: 768px)', 1)[1]

    assert '.game-details-page { width: 100% !important; margin: 0 0 24px !important; }' in storefront_mobile
    assert 'width: 100% !important;' in storefront_mobile
    assert 'margin: 0 !important;' in storefront_mobile
    assert '.game-status-btn-cover' in storefront_mobile
    assert 'width: 44px;' in storefront_mobile
    assert 'height: 44px;' in storefront_mobile
