"""Canonical defaults and merge helpers for global application settings."""

from copy import deepcopy
from typing import Any, Mapping

from sharewarez.branding import DEFAULT_BRAND_LOGO, DEFAULT_SITE_TITLE


MOBILE_NAV_ITEMS = ('discover', 'library', 'requests', 'downloads', 'favorites')
DEFAULT_DOWNLOAD_THREADS = 8
DEFAULT_DOWNLOAD_BATCH_SIZE = 200

DEFAULT_SETTINGS = {
    'siteTitle': DEFAULT_SITE_TITLE,
    'brandLogoPath': DEFAULT_BRAND_LOGO,
    'showSystemLogo': True,
    'showHelpButton': True,
    'enableWebLinksOnDetailsPage': True,
    'enableServerStatusFeature': True,
    'enableNewsletterFeature': True,
    'enableGameRequests': True,
    'enableGameIssues': True,
    'allowRequestNotes': True,
    'allowRequestAnyEdition': True,
    'maxActiveRequestsPerUser': 20,
    'notifyRequesterRequestEmail': True,
    'notifyAdminRequestEmail': False,
    'notifyDiscordNewRequests': False,
    'notifyDiscordRequestUpdates': False,
    'notifyAdminIssueEmail': True,
    'notifyReporterIssueEmail': True,
    'notifyAdminDownloadCancellations': False,
    'notifyAdminRepeatDownloads': False,
    'showVersion': True,
    'showDiscovery': True,
    'showFavorites': True,
    'showTrailers': True,
    'showPlayStatus': True,
    'mobileNavOrder': list(MOBILE_NAV_ITEMS),
    'enableDeleteGameOnDisk': True,
    'enableGameUpdates': True,
    'enableGameExtras': True,
    'siteUrl': 'http://127.0.0.1',
    'discordNotifyNewGames': False,
    'discordNotifyGameUpdates': False,
    'discordNotifyGameExtras': False,
    'discordNotifyDownloads': False,
    'discordNotifyManualTrigger': False,
    'updateFolderName': 'updates',
    'extrasFolderName': 'extras',
    'useTurboImageDownloads': True,
    'turboDownloadThreads': DEFAULT_DOWNLOAD_THREADS,
    'turboDownloadBatchSize': DEFAULT_DOWNLOAD_BATCH_SIZE,
    'maxConcurrentDownloadsPerUser': 2,
    'downloadBandwidthLimitMbps': 0,
    'downloadQueueWaitSeconds': 10,
    'downloadRequestExpirationHours': 168,
    'defaultMonthlyDownloadQuotaGb': 0,
    'archiveCacheMode': 'prefer',
    'archiveCacheMaxGb': 100,
    'archiveCacheMinFreeGb': 10,
    'archiveCacheRetentionDays': 7,
    'archiveCacheBuildConcurrency': 1,
    'archiveCacheFallbackEnabled': True,
    'scanThreadCount': 1,
    'enableHltbIntegration': True,
    'hltbRateLimitDelay': 2.0,
    'useLocalMetadata': False,
    'writeLocalMetadata': False,
    'useLocalImages': False,
    'localMetadataFilename': 'sharewarez.json',
}


def default_settings() -> dict[str, Any]:
    """Return a mutation-safe copy of the canonical defaults."""
    return deepcopy(DEFAULT_SETTINGS)


def merge_settings(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge stored values over a fresh copy of the canonical defaults."""
    settings = default_settings()
    if values:
        settings.update(values)
    return settings
