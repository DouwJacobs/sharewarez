"""Translate IGDB payloads into the editable game's shared form contract."""
from datetime import datetime, timezone


CATEGORY_NAMES = {
    0: 'MAIN_GAME', 1: 'DLC_ADDON', 2: 'EXPANSION', 3: 'BUNDLE',
    4: 'STANDALONE_EXPANSION', 5: 'MOD', 6: 'EPISODE', 7: 'SEASON',
    8: 'REMAKE', 9: 'REMASTER', 10: 'EXPANDED_GAME', 11: 'PORT',
    13: 'PACK', 14: 'UPDATE',
}
STATUS_NAMES = {0: 'RELEASED', 2: 'ALPHA', 3: 'BETA', 4: 'EARLY_ACCESS', 5: 'OFFLINE', 6: 'CANCELLED'}


def igdb_form_values(game):
    """Keep provider enums/nested fields out of browser-specific conversions."""
    values = {key: game.get(key) or '' for key in ('name', 'summary', 'storyline', 'url')}
    values['igdb_id'] = game.get('id')
    values['category'] = CATEGORY_NAMES.get(game.get('category'), '')
    values['status'] = STATUS_NAMES.get(game.get('status'), '')
    values['aggregated_rating'] = game.get('aggregated_rating')
    timestamp = game.get('first_release_date')
    try:
        values['first_release_date'] = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat() if timestamp else ''
    except (ValueError, TypeError, OverflowError, OSError):
        values['first_release_date'] = ''
    values['video_urls'] = ','.join(
        f"https://www.youtube.com/embed/{video['video_id']}"
        for video in game.get('videos') or [] if isinstance(video, dict) and video.get('video_id')
    )
    for field in ('genres', 'themes', 'game_modes', 'platforms', 'player_perspectives'):
        values[field] = [item['name'] for item in game.get(field) or []
                         if isinstance(item, dict) and item.get('name')]
    companies = [item for item in game.get('involved_companies') or [] if isinstance(item, dict)]
    for field, role in (('developer', 'developer'), ('publisher', 'publisher')):
        names = [item['company']['name'] for item in companies
                 if item.get(role) and isinstance(item.get('company'), dict) and item['company'].get('name')]
        values[field] = names[0] if names else ''
    return values


def with_form_values(game):
    return {**game, 'form_values': igdb_form_values(game)}
