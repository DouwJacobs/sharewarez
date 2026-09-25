from sharewarez import db
from sharewarez.branding import DEFAULT_BRAND_LOGO, resolve_site_title
from sharewarez.models import GlobalSettings
from sharewarez.settings_defaults import MOBILE_NAV_ITEMS, merge_settings
from sqlalchemy import select
from sharewarez import app_version
import json

MOBILE_NAV_DEFAULT = list(MOBILE_NAV_ITEMS)


def normalize_mobile_nav_order(value):
    if not isinstance(value, list) or len(value) != len(MOBILE_NAV_DEFAULT):
        return MOBILE_NAV_DEFAULT.copy()
    if set(value) != set(MOBILE_NAV_DEFAULT):
        return MOBILE_NAV_DEFAULT.copy()
    return value

def get_loc(page):
    
    with open(f'sharewarez/static/localization/en/{page}.json', 'r', encoding='utf8') as f:
            loc_data = json.load(f)    
    return loc_data

def get_global_settings():
    """Return the public template context derived from global settings."""
    settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    settings = merge_settings(settings_record.settings if settings_record else None)

    return {
        'site_title': resolve_site_title(settings),
        'brand_logo_path': settings.get('brandLogoPath') or DEFAULT_BRAND_LOGO,
        'show_logo': settings['showSystemLogo'],
        'show_help_button': settings['showHelpButton'],
        'enable_web_links': settings['enableWebLinksOnDetailsPage'],
        'enable_server_status': settings['enableServerStatusFeature'],
        'enable_newsletter': settings['enableNewsletterFeature'],
        'enable_game_requests': settings['enableGameRequests'],
        'enable_game_issues': settings['enableGameIssues'],
        'mobile_nav_order': normalize_mobile_nav_order(settings['mobileNavOrder']),
        'show_version': settings['showVersion'],
        'show_discovery': settings['showDiscovery'],
        'show_favorites': settings['showFavorites'],
        'show_trailers': settings['showTrailers'],
        'show_play_status': settings['showPlayStatus'],
        'enable_delete_game_on_disk': settings['enableDeleteGameOnDisk'],
        'enable_game_updates': settings['enableGameUpdates'],
        'enable_game_extras': settings['enableGameExtras'],
        'discord_configured': bool(settings_record and settings_record.discord_webhook_url),
        'discord_manual_trigger_enabled': bool(
            settings_record and settings_record.discord_notify_manual_trigger
        ),
        'app_version': app_version,
    }
