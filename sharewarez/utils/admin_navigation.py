"""Single source of truth for administrator navigation and search."""

from __future__ import annotations

from flask import request, url_for


ADMIN_NAVIGATION = (
    {
        'key': 'overview',
        'label': 'Overview',
        'icon': 'fa-gauge-high',
        'items': (
            {
                'key': 'dashboard', 'label': 'Admin overview',
                'description': 'Review work that needs attention and instance health.',
                'icon': 'fa-gauge-high', 'endpoint': 'site.admin_dashboard',
                'keywords': 'dashboard health attention overview',
            },
        ),
    },
    {
        'key': 'library',
        'label': 'Library',
        'icon': 'fa-book-open',
        'items': (
            {
                'key': 'libraries', 'label': 'Libraries',
                'description': 'Add, edit, and organize game libraries.',
                'icon': 'fa-book', 'endpoint': 'library.admin_libraries',
                'keywords': 'games content platforms library',
                'match_paths': ('/admin/library/',),
            },
            {
                'key': 'scan-manager', 'label': 'Scan manager',
                'description': 'Run scans and manage file detection, schedules, and artwork.',
                'icon': 'fa-magnifying-glass', 'endpoint': 'main.admin_scan_management',
                'keywords': 'scan files folders filters extensions images metadata',
                'match_paths': ('/scan_management', '/admin/extensions', '/admin/edit_filters', '/admin/image_queue'),
            },
            {
                'key': 'collections', 'label': 'Collections',
                'description': 'Create curated and smart game collections.',
                'icon': 'fa-layer-group', 'endpoint': 'admin2.collections',
                'keywords': 'curated smart groups',
            },
            {
                'key': 'discovery', 'label': 'Discovery',
                'description': 'Choose and order the sections members discover.',
                'icon': 'fa-compass', 'endpoint': 'admin2.discovery_sections',
                'keywords': 'homepage sections featured discover',
            },
        ),
    },
    {
        'key': 'community',
        'label': 'Community',
        'icon': 'fa-comments',
        'items': (
            {
                'key': 'requests', 'label': 'Game requests',
                'description': 'Review community demand and update request status.',
                'icon': 'fa-paper-plane', 'endpoint': 'game_requests.admin_requests',
                'keywords': 'requests demand editions members', 'feature_flag': 'enable_game_requests',
            },
            {
                'key': 'issues', 'label': 'Game issues',
                'description': 'Review reports, reply to users, and track resolutions.',
                'icon': 'fa-bug', 'endpoint': 'issues.admin_issues',
                'keywords': 'issues bugs reports problems support', 'feature_flag': 'enable_game_issues',
            },
            {
                'key': 'downloads', 'label': 'Download activity',
                'description': 'Monitor transfers and manage download requests.',
                'icon': 'fa-download', 'endpoint': 'download.manage_downloads',
                'keywords': 'downloads delivery transfers queue files',
            },
        ),
    },
    {
        'key': 'people',
        'label': 'People',
        'icon': 'fa-user-shield',
        'items': (
            {
                'key': 'users', 'label': 'Users',
                'description': 'Manage accounts, roles, quotas, and access.',
                'icon': 'fa-users-gear', 'endpoint': 'admin2.manage_users',
                'keywords': 'accounts roles members permissions quotas',
            },
            {
                'key': 'invitations', 'label': 'Invitations',
                'description': 'Create and review registration invitations.',
                'icon': 'fa-envelope-open-text', 'endpoint': 'admin2.manage_invites',
                'keywords': 'invites registration access',
            },
            {
                'key': 'whitelist', 'label': 'Whitelist',
                'description': 'Control which email addresses may register.',
                'icon': 'fa-list-check', 'endpoint': 'admin2.whitelist',
                'keywords': 'allowlist emails registration access',
            },
        ),
    },
    {
        'key': 'operations',
        'label': 'Operations',
        'icon': 'fa-server',
        'items': (
            {
                'key': 'jobs', 'label': 'Background jobs',
                'description': 'Monitor queued work, progress, and failures.',
                'icon': 'fa-list-check', 'endpoint': 'admin2.background_jobs',
                'keywords': 'jobs worker queue tasks failures schedules',
            },
            {
                'key': 'logs', 'label': 'System logs',
                'description': 'Search operational, audit, and security events.',
                'icon': 'fa-clipboard-list', 'endpoint': 'admin2.system_logs',
                'keywords': 'logs events audit errors warnings security',
            },
            {
                'key': 'status', 'label': 'Server status',
                'description': 'Review runtime, storage, database, and integration health.',
                'icon': 'fa-heart-pulse', 'endpoint': 'info.server_status',
                'keywords': 'server health storage database cpu memory diagnostics',
                'feature_flag': 'enable_server_status',
                'match_paths': ('/admin/server_status_page', '/admin/new_server_info'),
            },
            {
                'key': 'statistics', 'label': 'Statistics',
                'description': 'Review download, collection, and invitation trends.',
                'icon': 'fa-chart-column', 'endpoint': 'download.statistics',
                'keywords': 'analytics reporting trends activity',
            },
        ),
    },
    {
        'key': 'configure',
        'label': 'Configure',
        'icon': 'fa-sliders',
        'items': (
            {
                'key': 'settings', 'label': 'Application settings',
                'description': 'Configure global features and workflow policies.',
                'icon': 'fa-sliders', 'endpoint': 'admin2.settings',
                'keywords': 'settings configuration policies features notifications interface',
                'match_paths': ('/admin/new_server_settings',),
                'exclude_query': {'section': 'notifications'},
            },
            {
                'key': 'notification-rules', 'label': 'Notification rules',
                'description': 'Choose which user and admin events send alerts.',
                'icon': 'fa-bell', 'endpoint': 'admin2.settings',
                'query_args': {'section': 'notifications'},
                'keywords': 'notifications email push discord requests issues downloads alerts',
                'match_paths': ('/admin/new_server_settings',),
            },
            {
                'key': 'integrations', 'label': 'Integrations',
                'description': 'Connect and test SMTP, IGDB, and Discord.',
                'icon': 'fa-plug', 'endpoint': 'admin2.integrations',
                'keywords': 'smtp email igdb discord webhook credentials',
                'match_paths': ('/admin/smtp_settings', '/admin/igdb_settings', '/admin/discord_settings'),
            },
            {
                'key': 'branding', 'label': 'Branding',
                'description': 'Update the site name, logo, and identity.',
                'icon': 'fa-signature', 'endpoint': 'admin2.branding',
                'keywords': 'appearance logo title identity',
            },
            {
                'key': 'themes', 'label': 'Themes',
                'description': 'Install, build, edit, and select visual themes.',
                'icon': 'fa-palette', 'endpoint': 'admin2.manage_themes',
                'keywords': 'appearance colors visual design builder',
            },
            {
                'key': 'attract-mode', 'label': 'Attract mode',
                'description': 'Configure idle trailer playback and presentation.',
                'icon': 'fa-tv', 'endpoint': 'admin2.attract_mode_settings_page',
                'keywords': 'appearance trailers idle display experience',
            },
            {
                'key': 'newsletter', 'label': 'Newsletter',
                'description': 'Compose and review library announcements.',
                'icon': 'fa-newspaper', 'endpoint': 'admin2.newsletter',
                'keywords': 'communication campaigns announcements email',
                'feature_flag': 'enable_newsletter',
            },
            {
                'key': 'email-templates', 'label': 'Email templates',
                'description': 'Customize transactional email content.',
                'icon': 'fa-envelope', 'endpoint': 'admin2.email_templates',
                'keywords': 'communication messages templates email notifications',
            },
        ),
    },
)


def build_admin_navigation(settings):
    """Resolve enabled admin destinations for templates and API search."""
    groups = []
    for group in ADMIN_NAVIGATION:
        items = []
        for definition in group['items']:
            flag = definition.get('feature_flag')
            if flag and not settings.get(flag, False):
                continue
            item = dict(definition)
            item['url'] = url_for(item['endpoint'], **item.get('query_args', {}))
            canonical_path = item['url'].split('?', 1)[0]
            prefixes = (canonical_path, *item.get('match_paths', ()))
            path_matches = any(
                request.path == prefix or request.path.startswith(prefix.rstrip('/') + '/')
                for prefix in prefixes
            )
            query_matches = all(
                request.args.get(key) == value
                for key, value in item.get('query_args', {}).items()
            )
            query_excluded = any(
                request.args.get(key) == value
                for key, value in item.get('exclude_query', {}).items()
            )
            item['active'] = path_matches and query_matches and not query_excluded
            items.append(item)
        if items:
            resolved = dict(group)
            resolved['items'] = items
            resolved['active'] = any(item['active'] for item in items)
            groups.append(resolved)
    return groups


def flatten_admin_navigation(settings):
    return [item for group in build_admin_navigation(settings) for item in group['items']]
