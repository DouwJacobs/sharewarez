from sharewarez import db
from sharewarez.branding import DEFAULT_BRAND_LOGO, DEFAULT_SITE_TITLE, resolve_site_title
from sharewarez.models import GlobalSettings
from sqlalchemy import select
from sharewarez import app_version
import json

MOBILE_NAV_DEFAULT = ['discover', 'library', 'requests', 'downloads', 'favorites']


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
    """Helper function to get global settings with defaults"""
    settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    default_settings = {
        'siteTitle': DEFAULT_SITE_TITLE,
        'brandLogoPath': DEFAULT_BRAND_LOGO,
        'showSystemLogo': True,
        'showHelpButton': True,
        'allowUsersToInviteOthers': False,
        'enableGameUpdates': True,
        'updateFolderName': 'updates',
        'enableGameExtras': True,
        'extrasFolderName': 'extras',
        'discordNotifyNewGames': False,
        'discordNotifyGameUpdates': False,
        'discordNotifyGameExtras': False,
        'discordNotifyDownloads': False,
        'siteUrl': 'http://127.0.0.1',
        'enableWebLinksOnDetailsPage': True,
        'enableServerStatusFeature': True,
        'enableNewsletterFeature': True,
        'enableGameRequests': True,
        'enableGameIssues': True,
        'mobileNavOrder': MOBILE_NAV_DEFAULT.copy(),
        'showVersion': True,
        'defaultTheme': 'default',
        'enableDeleteGameOnDisk': True,
    }
    
    settings = default_settings.copy()
    
    if settings_record and settings_record.settings:
        settings.update(settings_record.settings)
        return {
            'site_title': resolve_site_title(settings),
            'brand_logo_path': settings.get('brandLogoPath') or DEFAULT_BRAND_LOGO,
            'show_logo': settings.get('showSystemLogo'),
            'show_help_button': settings.get('showHelpButton'),
            'enable_web_links': settings.get('enableWebLinksOnDetailsPage'),
            'enable_server_status': settings_record.settings.get('enableServerStatusFeature', False),
            'enable_newsletter': settings_record.settings.get('enableNewsletterFeature', False),
            'enable_game_requests': settings.get('enableGameRequests', True),
            'enable_game_issues': settings.get('enableGameIssues', True),
            'mobile_nav_order': normalize_mobile_nav_order(settings.get('mobileNavOrder')),
            'show_version': settings_record.settings.get('showVersion', False),
            'show_discovery': settings.get('showDiscovery', True),
            'show_favorites': settings.get('showFavorites', True),
            'show_trailers': settings.get('showTrailers', True),
            'show_play_status': settings.get('showPlayStatus', True),
            'enable_delete_game_on_disk': settings_record.settings.get('enableDeleteGameOnDisk', True),
            'enable_game_updates': settings_record.settings.get('enableGameUpdates', True),
            'enable_game_extras': settings_record.settings.get('enableGameExtras', True),
            'discord_configured': bool(settings_record.discord_webhook_url),
            'discord_manual_trigger_enabled': settings_record.discord_notify_manual_trigger if settings_record else False,
            'app_version': app_version
        }
    
    # Return default values if no settings_record is found
    return {
        'site_title': DEFAULT_SITE_TITLE,
        'brand_logo_path': DEFAULT_BRAND_LOGO,
        'show_logo': True,
        'show_help_button': True,
        'enable_web_links': True,
        'enable_server_status': True,
        'enable_newsletter': True,
        'enable_game_requests': True,
        'enable_game_issues': True,
        'mobile_nav_order': MOBILE_NAV_DEFAULT.copy(),
        'show_version': True,
        'show_discovery': True,
        'show_favorites': True,
        'show_trailers': True,
        'show_play_status': True,
        'enable_delete_game_on_disk': True,
        'enable_game_updates': True,
        'enable_game_extras': True,
        'discord_configured': False,
        'discord_manual_trigger_enabled': False,
        'app_version': app_version
    }
