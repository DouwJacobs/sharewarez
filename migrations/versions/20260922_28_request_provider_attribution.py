"""Store request provider source and attribution metadata.

Revision ID: 20260922_28
Revises: 20260922_27
"""

from alembic import op
import sqlalchemy as sa


revision = '20260922_28'
down_revision = '20260922_27'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'game_requests',
        sa.Column('provider_url', sa.String(length=1024), nullable=True),
    )
    op.add_column(
        'game_requests',
        sa.Column('provider_attribution', sa.JSON(), nullable=True),
    )
    op.execute(sa.text(
        "UPDATE game_requests SET "
        "provider_url = 'https://www.igdb.com/', "
        "provider_attribution = '{\"name\": \"IGDB\", "
        "\"url\": \"https://www.igdb.com/\"}'::json "
        "WHERE metadata_provider = 'igdb'"
    ))


def downgrade():
    op.drop_column('game_requests', 'provider_attribution')
    op.drop_column('game_requests', 'provider_url')
