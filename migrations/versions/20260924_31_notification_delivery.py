"""add unified notification events and outbound webhooks

Revision ID: 20260924_31
Revises: 20260923_30
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa
import json


revision = '20260924_31'
down_revision = '20260923_30'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if 'notification_events' not in tables:
        op.create_table(
            'notification_events',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('event_type', sa.String(length=64), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('link_url', sa.String(length=1024), nullable=True),
            sa.Column('resource_type', sa.String(length=64), nullable=True),
            sa.Column('resource_id', sa.String(length=255), nullable=True),
            sa.Column('event_data', sa.Text(), nullable=False),
            sa.Column('dedupe_key', sa.String(length=255), nullable=True),
            sa.Column('is_test', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('event_type', 'dedupe_key', name='uq_notification_event_key'),
        )
        op.create_index('ix_notification_events_event_type', 'notification_events', ['event_type'])
        op.create_index('ix_notification_events_created_at', 'notification_events', ['created_at'])
    notification_columns = {
        column['name'] for column in sa.inspect(connection).get_columns('notifications')
    }
    if 'event_id' not in notification_columns:
        op.add_column('notifications', sa.Column('event_id', sa.String(length=36), nullable=True))
        op.create_foreign_key(
            'fk_notifications_event_id_notification_events', 'notifications',
            'notification_events', ['event_id'], ['id'], ondelete='SET NULL',
        )
        op.create_index('ix_notifications_event_id', 'notifications', ['event_id'])
    if 'webhook_endpoints' not in tables:
        op.create_table(
            'webhook_endpoints',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('signing_secret', sa.Text(), nullable=False),
            sa.Column('subscribed_events', sa.Text(), nullable=False),
            sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
        )
        op.create_index('ix_webhook_endpoints_is_enabled', 'webhook_endpoints', ['is_enabled'])
    if 'webhook_deliveries' not in tables:
        op.create_table(
            'webhook_deliveries',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('endpoint_id', sa.String(length=36), nullable=False),
            sa.Column('event_id', sa.String(length=36), nullable=False),
            sa.Column('payload', sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='queued'),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('response_status', sa.Integer(), nullable=True),
            sa.Column('response_excerpt', sa.String(length=2048), nullable=True),
            sa.Column('error_message', sa.String(length=2048), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['endpoint_id'], ['webhook_endpoints.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['event_id'], ['notification_events.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('endpoint_id', 'event_id', name='uq_webhook_endpoint_event'),
        )
        for name, columns in (
            ('ix_webhook_deliveries_endpoint_id', ['endpoint_id']),
            ('ix_webhook_deliveries_event_id', ['event_id']),
            ('ix_webhook_deliveries_status', ['status']),
            ('ix_webhook_deliveries_created_at', ['created_at']),
            ('ix_webhook_deliveries_recent', ['endpoint_id', 'created_at']),
        ):
            op.create_index(name, 'webhook_deliveries', columns)

    event_categories = {
        'new_game': 'games', 'game_update': 'games',
        'download_archive_ready': 'downloads',
        'request_created': 'requests', 'request_updated': 'requests',
        'issue_created': 'issues', 'issue_comment': 'issues',
        'issue_status': 'issues', 'issue_deleted': 'issues',
        'download_cancelled': 'downloads', 'download_repeated': 'downloads',
    }
    rows = connection.execute(sa.text(
        'SELECT id, experience_settings FROM user_preferences'
    )).mappings()
    for row in rows:
        try:
            experience = json.loads(row['experience_settings'] or '{}')
        except (TypeError, ValueError):
            experience = {}
        notifications = experience.get('notifications')
        notifications = notifications if isinstance(notifications, dict) else {}
        events = {}
        for event_type, category in event_categories.items():
            category_enabled = bool(notifications.get(category, True))
            events[event_type] = {
                'in_app': category_enabled,
                'email': True,
                'push': category_enabled and bool(notifications.get('browser', True)),
            }
        notifications['version'] = 2
        notifications['events'] = events
        experience['notifications'] = notifications
        connection.execute(
            sa.text('UPDATE user_preferences SET experience_settings = :value WHERE id = :id'),
            {'id': row['id'], 'value': json.dumps(experience)},
        )

    settings_row = connection.execute(sa.text(
        'SELECT id, settings, discord_notify_new_games, discord_notify_game_updates, '
        'discord_notify_downloads FROM global_settings ORDER BY id LIMIT 1'
    )).mappings().first()
    if settings_row:
        try:
            values = json.loads(settings_row['settings'] or '{}')
        except (TypeError, ValueError):
            values = {}
        email = {
            'request_created': bool(values.get('notifyAdminRequestEmail', False)),
            'request_updated': bool(values.get('notifyRequesterRequestEmail', True)),
            'issue_created': bool(values.get('notifyAdminIssueEmail', True)),
            'issue_comment': bool(values.get('notifyAdminIssueEmail', True) or values.get('notifyReporterIssueEmail', True)),
            'issue_status': bool(values.get('notifyAdminIssueEmail', True) or values.get('notifyReporterIssueEmail', True)),
            'issue_deleted': bool(values.get('notifyReporterIssueEmail', True)),
        }
        discord = {
            'new_game': bool(settings_row['discord_notify_new_games']),
            'game_update': bool(settings_row['discord_notify_game_updates']),
            'download_archive_ready': bool(settings_row['discord_notify_downloads']),
            'request_created': bool(values.get('notifyDiscordNewRequests', False)),
            'request_updated': bool(values.get('notifyDiscordRequestUpdates', False)),
        }
        policy = {}
        for event_type in event_categories:
            event_enabled = {
                'download_cancelled': bool(values.get('notifyAdminDownloadCancellations', False)),
                'download_repeated': bool(values.get('notifyAdminRepeatDownloads', False)),
            }.get(event_type, True)
            policy[event_type] = {
                'in_app': event_enabled,
                'email': email.get(event_type, False),
                'push': event_enabled,
                'discord': discord.get(event_type, False),
            }
        values['notificationPolicy'] = policy
        connection.execute(
            sa.text('UPDATE global_settings SET settings = :value WHERE id = :id'),
            {'id': settings_row['id'], 'value': json.dumps(values)},
        )


def downgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        'SELECT id, experience_settings FROM user_preferences'
    )).mappings()
    for row in rows:
        try:
            experience = json.loads(row['experience_settings'] or '{}')
        except (TypeError, ValueError):
            continue
        notifications = experience.get('notifications')
        if isinstance(notifications, dict):
            notifications.pop('version', None)
            notifications.pop('events', None)
            experience['notifications'] = notifications
            connection.execute(
                sa.text('UPDATE user_preferences SET experience_settings = :value WHERE id = :id'),
                {'id': row['id'], 'value': json.dumps(experience)},
            )
    settings_rows = connection.execute(sa.text('SELECT id, settings FROM global_settings')).mappings()
    for row in settings_rows:
        try:
            values = json.loads(row['settings'] or '{}')
        except (TypeError, ValueError):
            continue
        values.pop('notificationPolicy', None)
        connection.execute(
            sa.text('UPDATE global_settings SET settings = :value WHERE id = :id'),
            {'id': row['id'], 'value': json.dumps(values)},
        )
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if 'webhook_deliveries' in tables:
        op.drop_table('webhook_deliveries')
    if 'webhook_endpoints' in tables:
        op.drop_table('webhook_endpoints')
    notification_columns = {
        column['name'] for column in inspector.get_columns('notifications')
    }
    if 'event_id' in notification_columns:
        indexes = {index['name'] for index in inspector.get_indexes('notifications')}
        if 'ix_notifications_event_id' in indexes:
            op.drop_index('ix_notifications_event_id', table_name='notifications')
        foreign_keys = inspector.get_foreign_keys('notifications')
        for foreign_key in foreign_keys:
            if foreign_key['constrained_columns'] == ['event_id'] and foreign_key.get('name'):
                op.drop_constraint(foreign_key['name'], 'notifications', type_='foreignkey')
                break
        op.drop_column('notifications', 'event_id')
    if 'notification_events' in tables:
        op.drop_table('notification_events')
