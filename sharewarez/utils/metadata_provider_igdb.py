"""IGDB API adapter for normalized metadata discovery operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Callable


IGDB_GAMES_ENDPOINT = 'https://api.igdb.com/v4/games'
IGDB_GAME_VERSIONS_ENDPOINT = 'https://api.igdb.com/v4/game_versions'
IGDB_REQUEST_FIELDS = (
    'fields id,name,version_parent.name,version_title,cover.image_id,summary,'
    'platforms.name,first_release_date;'
)


def _cover_url(game_data):
    cover = game_data.get('cover') or {}
    image_id = cover.get('image_id') if isinstance(cover, dict) else None
    return f'https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg' if image_id else None


def _parent_id(game_data):
    parent = game_data.get('version_parent')
    if isinstance(parent, dict):
        return int(parent.get('id') or game_data['id'])
    return int(parent or game_data['id'])


def normalize_igdb_game(game_data):
    """Translate an IGDB game response into Sharewarez discovery fields."""
    release_timestamp = game_data.get('first_release_date')
    release_date = None
    if release_timestamp:
        release_date = datetime.fromtimestamp(int(release_timestamp), tz=timezone.utc)
    parent = game_data.get('version_parent')
    parent_name = parent.get('name') if isinstance(parent, dict) else None
    return {
        'igdb_id': int(game_data['id']),
        'parent_igdb_id': _parent_id(game_data),
        'parent_game_name': str(parent_name or game_data.get('name') or '').strip(),
        'game_name': str(game_data.get('name') or '').strip(),
        'edition_name': str(game_data.get('version_title') or '').strip() or None,
        'cover_url': _cover_url(game_data),
        'summary': str(game_data.get('summary') or '').strip() or None,
        'platforms': [
            item.get('name') for item in game_data.get('platforms', [])
            if isinstance(item, dict) and item.get('name')
        ],
        'first_release_date': release_date,
    }


@dataclass(frozen=True)
class IGDBMetadataProvider:
    """Normalized discovery operations backed only by IGDB's public API."""

    request: Callable[[str, str], object]
    name: str = 'igdb'

    def fetch_game(self, igdb_id):
        response = self.request(
            IGDB_GAMES_ENDPOINT,
            f'{IGDB_REQUEST_FIELDS} where id = {int(igdb_id)}; limit 1;',
        )
        if not isinstance(response, list) or not response:
            return None
        return normalize_igdb_game(response[0])

    def search_games(self, term):
        safe_term = re.sub(r"[^\w\s\-:&+().'\u00c0-\u024f]", ' ', term).strip()
        response = self.request(
            IGDB_GAMES_ENDPOINT,
            f'{IGDB_REQUEST_FIELDS} search "{safe_term}"; limit 10;',
        )
        if not isinstance(response, list):
            error = response.get('error') if isinstance(response, dict) else 'IGDB search failed'
            return [], error
        return [normalize_igdb_game(item) for item in response], None

    def fetch_related_editions(self, igdb_id):
        selected = self.fetch_game(igdb_id)
        if not selected:
            return []
        parent_id = selected['parent_igdb_id']

        related_games = self.request(
            IGDB_GAMES_ENDPOINT,
            f'{IGDB_REQUEST_FIELDS} where id = {parent_id} | version_parent = {parent_id}; limit 50;',
        )
        related_by_id = {}
        if isinstance(related_games, list):
            related_by_id.update(
                (item['igdb_id'], item)
                for item in (normalize_igdb_game(game) for game in related_games)
            )
        related_by_id[selected['igdb_id']] = selected

        versions = self.request(
            IGDB_GAME_VERSIONS_ENDPOINT,
            f'fields games; where game = {parent_id}; limit 50;',
        )
        edition_ids = {parent_id, int(igdb_id)}
        if isinstance(versions, list):
            for version in versions:
                edition_ids.update(int(value) for value in (version.get('games') or []))
        missing_ids = edition_ids.difference(related_by_id)
        if missing_ids:
            ids = ','.join(str(value) for value in sorted(missing_ids))
            response = self.request(
                IGDB_GAMES_ENDPOINT,
                f'{IGDB_REQUEST_FIELDS} where id = ({ids}); limit 50;',
            )
            if isinstance(response, list):
                related_by_id.update(
                    (item['igdb_id'], item)
                    for item in (normalize_igdb_game(game) for game in response)
                )
        return sorted(
            related_by_id.values(),
            key=lambda item: (item['igdb_id'] != parent_id, item['game_name']),
        )
