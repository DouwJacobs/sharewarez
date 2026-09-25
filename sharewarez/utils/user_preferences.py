"""Helpers for account-scoped UI and notification preferences."""

from copy import deepcopy

from sharewarez import db
from sharewarez.models import UserPreference


DEFAULT_EXPERIENCE_SETTINGS = {
    'library_view': 'grid',
    'saved_library_views': [],
    'discover_hidden_sections': [],
    'discover_section_order': [],
    'recently_viewed_game_uuids': [],
    'notifications': {
        'requests': True,
        'issues': True,
        'downloads': True,
        'games': True,
        'browser': True,
    },
}

NOTIFICATION_CATEGORIES = ('requests', 'issues', 'downloads', 'games')


def get_or_create_user_preferences(user):
    preferences = user.preferences
    if preferences is None:
        preferences = UserPreference(user_id=user.id)
        db.session.add(preferences)
    return preferences


def get_experience_settings(user):
    """Return a defensive, default-filled copy of the user's UI settings."""
    settings = deepcopy(DEFAULT_EXPERIENCE_SETTINGS)
    preferences = user.preferences
    stored = preferences.experience_settings if preferences else None
    if not isinstance(stored, dict):
        return settings

    for key in (
        'library_view', 'saved_library_views', 'discover_hidden_sections',
        'discover_section_order', 'recently_viewed_game_uuids',
    ):
        if key in stored:
            settings[key] = deepcopy(stored[key])
    if isinstance(stored.get('notifications'), dict):
        settings['notifications'].update(stored['notifications'])
    return settings


def update_experience_settings(user, **updates):
    preferences = get_or_create_user_preferences(user)
    settings = get_experience_settings(user)
    for key, value in updates.items():
        if key == 'notifications' and isinstance(value, dict):
            settings['notifications'].update(value)
        elif key in settings:
            settings[key] = deepcopy(value)
    preferences.experience_settings = settings
    return preferences


def notification_category(event_type):
    value = (event_type or '').lower()
    if 'request' in value:
        return 'requests'
    if 'issue' in value:
        return 'issues'
    if 'download' in value:
        return 'downloads'
    return 'games'


def notification_enabled(user, event_type, *, browser=False):
    from sharewarez.utils.notification_events import EVENTS, personal_preferences

    if event_type in EVENTS:
        channel = 'push' if browser else 'in_app'
        return personal_preferences(user)[event_type][channel]
    settings = get_experience_settings(user)['notifications']
    category = notification_category(event_type)
    return bool(settings.get(category, True)) and (
        not browser or bool(settings.get('browser', True))
    )


def remember_recent_game(user, game_uuid, limit=12):
    settings = get_experience_settings(user)
    recent = [value for value in settings['recently_viewed_game_uuids'] if value != game_uuid]
    recent.insert(0, game_uuid)
    update_experience_settings(user, recently_viewed_game_uuids=recent[:limit])
