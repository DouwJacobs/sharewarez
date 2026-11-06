from sharewarez.utils.admin_navigation import ADMIN_NAVIGATION, build_admin_navigation


def test_admin_navigation_metadata_has_unique_groups_and_destinations():
    group_keys = [group['key'] for group in ADMIN_NAVIGATION]
    item_keys = [item['key'] for group in ADMIN_NAVIGATION for item in group['items']]

    assert group_keys == ['overview', 'library', 'community', 'people', 'operations', 'configure']
    assert len(group_keys) == len(set(group_keys))
    assert len(item_keys) == len(set(item_keys))
    assert all(item['label'] and item['description'] and item['icon'] for group in ADMIN_NAVIGATION for item in group['items'])


def test_notification_deep_link_activates_the_single_settings_destination(app):
    settings = {
        'enable_game_requests': True,
        'enable_game_issues': True,
        'enable_server_status': True,
        'enable_newsletter': True,
    }
    with app.test_request_context('/admin/settings?section=notifications'):
        groups = build_admin_navigation(settings)

    configure = next(group for group in groups if group['key'] == 'configure')
    application_settings = next(item for item in configure['items'] if item['key'] == 'settings')
    assert not any(item['key'] == 'notification-rules' for item in configure['items'])
    assert application_settings['url'] == '/admin/settings'
    assert application_settings['active'] is True
    assert configure['active'] is True


def test_feature_flags_remove_disabled_admin_destinations(app):
    with app.test_request_context('/admin/dashboard'):
        groups = build_admin_navigation({})

    keys = {item['key'] for group in groups for item in group['items']}
    assert {'requests', 'issues', 'status', 'newsletter'}.isdisjoint(keys)
    assert {'dashboard', 'libraries', 'settings', 'integrations'} <= keys
