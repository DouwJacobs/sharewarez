"""RAWG API adapter for normalized metadata discovery operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Callable, Mapping
from urllib.parse import quote

import requests


RAWG_API_ROOT = 'https://api.rawg.io/api'
RAWG_SITE_ROOT = 'https://rawg.io'
RAWG_MAX_ATTEMPTS = 3
RAWG_TIMEOUT_SECONDS = 10


def _release_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _provider_url(game_data):
    slug = str(game_data.get('slug') or '').strip()
    if not slug:
        return RAWG_SITE_ROOT
    return f'{RAWG_SITE_ROOT}/games/{quote(slug, safe="-")}'


def normalize_rawg_game(game_data):
    """Translate a RAWG game response into provider-neutral discovery fields."""
    external_id = str(game_data['id'])
    provider_url = _provider_url(game_data)
    platforms = []
    for item in game_data.get('platforms') or []:
        platform = item.get('platform') if isinstance(item, dict) else None
        if isinstance(platform, dict) and platform.get('name'):
            platforms.append(platform['name'])
    return {
        'provider': 'rawg',
        'provider_game_id': external_id,
        'provider_parent_id': external_id,
        'provider_url': provider_url,
        'attribution': {'name': 'RAWG', 'url': provider_url},
        'game_name': str(game_data.get('name') or '').strip(),
        'parent_game_name': str(game_data.get('name') or '').strip(),
        'edition_name': None,
        'cover_url': str(game_data.get('background_image') or '').strip() or None,
        'summary': (
            str(game_data.get('description_raw') or '').strip()
            or None
        ),
        'platforms': platforms,
        'first_release_date': _release_date(game_data.get('released')),
        'genres': [
            item['name'] for item in (game_data.get('genres') or [])
            if isinstance(item, dict) and item.get('name')
        ],
        'developers': [
            item['name'] for item in (game_data.get('developers') or [])
            if isinstance(item, dict) and item.get('name')
        ],
        'publishers': [
            item['name'] for item in (game_data.get('publishers') or [])
            if isinstance(item, dict) and item.get('name')
        ],
        'rating': game_data.get('rating'),
        'rating_count': game_data.get('ratings_count'),
        'website': str(game_data.get('website') or '').strip() or None,
    }


@dataclass
class RawgAPIClient:
    """Small authenticated RAWG client with bounded transient retries."""

    api_key: str
    session: object = requests
    timeout: int = RAWG_TIMEOUT_SECONDS
    max_attempts: int = RAWG_MAX_ATTEMPTS
    sleep: Callable[[float], None] = time.sleep

    def get(self, path: str, params: Mapping | None = None):
        normalized_path = '/' + str(path).strip().lstrip('/')
        request_params = dict(params or {})
        request_params['key'] = self.api_key
        for attempt in range(self.max_attempts):
            try:
                response = self.session.get(
                    f'{RAWG_API_ROOT}{normalized_path}',
                    params=request_params,
                    timeout=self.timeout,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_attempts - 1:
                        self.sleep(0.5 * (2 ** attempt))
                        continue
                    return {'error': 'RAWG is temporarily unavailable'}
                if response.status_code in {401, 403}:
                    return {'error': 'RAWG credentials were rejected'}
                if response.status_code >= 400:
                    return {'error': 'RAWG request failed'}
                payload = response.json()
                return payload if isinstance(payload, (dict, list)) else {
                    'error': 'RAWG returned an invalid response'
                }
            except (requests.RequestException, ValueError):
                if attempt < self.max_attempts - 1:
                    self.sleep(0.5 * (2 ** attempt))
                    continue
                return {'error': 'RAWG request failed'}
        return {'error': 'RAWG request failed'}


@dataclass(frozen=True)
class RAWGMetadataProvider:
    """Normalized discovery operations backed only by RAWG's documented API."""

    request: Callable[[str, Mapping | None], object]
    name: str = 'rawg'

    def search_games(self, term):
        payload = self.request('/games', {
            'search': str(term).strip(),
            'page_size': 10,
        })
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            error = payload.get('error') if isinstance(payload, dict) else 'RAWG search failed'
            return [], error
        return [normalize_rawg_game(item) for item in payload['results']], None

    def fetch_game(self, external_id):
        payload = self.request(f'/games/{quote(str(external_id), safe="")}', None)
        if not isinstance(payload, dict) or payload.get('error') or 'id' not in payload:
            return None
        return normalize_rawg_game(payload)

    def fetch_game_payload(self, external_id):
        payload = self.request(f'/games/{quote(str(external_id), safe="")}', None)
        if not isinstance(payload, dict) or payload.get('error') or 'id' not in payload:
            error = payload.get('error') if isinstance(payload, dict) else 'RAWG game lookup failed'
            return None, error
        return normalize_rawg_game(payload), None

    def fetch_media(self, external_id):
        game = self.fetch_game(external_id)
        if not game:
            return None, 'RAWG returned no matching game'
        screenshots = self.request(
            f'/games/{quote(str(external_id), safe="")}/screenshots',
            {'page_size': 100},
        )
        screenshot_results = (
            screenshots.get('results', []) if isinstance(screenshots, dict) else []
        )
        return {
            'cover': game.get('cover_url'),
            'screenshots': [
                item['image'] for item in screenshot_results
                if isinstance(item, dict) and item.get('image')
            ],
            'artworks': [],
        }, None
