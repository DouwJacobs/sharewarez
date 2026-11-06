"""Explicit ownership boundaries for partial Application Settings updates."""
SECTION_KEYS = {
    'general': frozenset(('allowUsersToInviteOthers', 'enableServerStatusFeature', 'enableNewsletterFeature', 'enableDeleteGameOnDisk', 'showPlayStatus', 'siteUrl')),
    'scanning': frozenset(('enableGameUpdates', 'updateFolderName', 'enableGameExtras', 'extrasFolderName', 'scanThreadCount', 'turboDownloadThreads', 'turboDownloadBatchSize', 'useTurboImageDownloads')),
    'downloads': frozenset(('maxConcurrentDownloadsPerUser', 'downloadBandwidthLimitMbps', 'defaultMonthlyDownloadQuotaGb', 'downloadQueueWaitSeconds', 'downloadRequestExpirationHours')),
    'metadata': frozenset(('enableHltbIntegration', 'hltbRateLimitDelay', 'useLocalMetadata', 'writeLocalMetadata', 'useLocalImages', 'localMetadataFilename')),
    'interface': frozenset(('showSystemLogo', 'showHelpButton', 'enableWebLinksOnDetailsPage', 'showVersion', 'showDiscovery', 'showFavorites', 'showTrailers', 'mobileNavOrder')),
    'requests': frozenset(('enableGameRequests', 'enableGameIssues', 'allowRequestNotes', 'allowRequestAnyEdition', 'maxActiveRequestsPerUser')),
    'notifications': frozenset(('notificationPolicy',)),
}


def settings_patch(data):
    if not isinstance(data, dict) or not data:
        raise ValueError('Settings data must be a nonempty JSON object')
    # Flat JSON remains the compatible legacy contract; envelopes cannot leak
    # transport metadata into the persisted settings document.
    if 'section' not in data and 'settings' not in data:
        return data
    if set(data) != {'section', 'settings'}:
        raise ValueError('Send section and settings as separate fields')
    section, changes = data['section'], data['settings']
    if not isinstance(section, str) or section not in SECTION_KEYS or not isinstance(changes, dict):
        raise ValueError('Unknown settings section or invalid changes')
    if set(changes) - SECTION_KEYS[section]:
        raise ValueError('This section cannot change the supplied settings')
    return changes



def locked_settings():
    """Reload the current singleton under a row lock; serialize first creation."""
    from sqlalchemy import select, text
    from sharewarez import db
    from sharewarez.models import GlobalSettings
    query = select(GlobalSettings).order_by(GlobalSettings.id).with_for_update().execution_options(populate_existing=True)
    settings_record = db.session.execute(query).scalars().first()
    if settings_record is None and db.engine.dialect.name == 'postgresql':
        # Serialize creation only when startup has not yet installed the singleton.
        db.session.execute(text('SELECT pg_advisory_xact_lock(716393501)'))
        settings_record = db.session.execute(query).scalars().first()
    if settings_record is None:
        settings_record = GlobalSettings(settings={})
        db.session.add(settings_record)
        db.session.flush()  # Ensure record has an ID
    return settings_record
