"""Add metadata provider configuration and encrypted RAWG credentials.

Revision ID: 20260922_27
Revises: 20260922_26
"""

from alembic import op
import sqlalchemy as sa


revision = '20260922_27'
down_revision = '20260922_26'
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column['name']
        for column in sa.inspect(op.get_bind()).get_columns('global_settings')
    }
    if 'rawg_api_key' not in columns:
        op.add_column(
        'global_settings',
        sa.Column('rawg_api_key', sa.Text(), nullable=True),
        )
    if 'rawg_enabled' not in columns:
        op.add_column(
        'global_settings',
        sa.Column(
            'rawg_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        )
    if 'rawg_last_tested' not in columns:
        op.add_column(
        'global_settings',
        sa.Column('rawg_last_tested', sa.DateTime(), nullable=True),
        )
    if 'metadata_provider_order' not in columns:
        op.add_column(
        'global_settings',
        sa.Column(
            'metadata_provider_order',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"igdb\"]'::json"),
        ),
        )


def downgrade():
    op.drop_column('global_settings', 'metadata_provider_order')
    op.drop_column('global_settings', 'rawg_last_tested')
    op.drop_column('global_settings', 'rawg_enabled')
    op.drop_column('global_settings', 'rawg_api_key')
