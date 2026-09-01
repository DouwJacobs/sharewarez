"""Keep durable game attribution on download transfers.

Revision ID: 20260901_22
Revises: 20260824_21
"""

from alembic import op
import sqlalchemy as sa


revision = '20260901_22'
down_revision = '20260824_21'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('download_transfers', sa.Column('game_uuid', sa.String(length=36), nullable=True))
    op.create_index('ix_download_transfers_game_uuid', 'download_transfers', ['game_uuid'])
    op.create_foreign_key(
        'fk_download_transfers_game_uuid_games',
        'download_transfers', 'games', ['game_uuid'], ['uuid'], ondelete='SET NULL',
    )
    op.execute(
        """
        UPDATE download_transfers AS transfer
        SET game_uuid = request.game_uuid
        FROM download_requests AS request
        WHERE transfer.download_request_id = request.id
          AND transfer.game_uuid IS NULL
        """
    )


def downgrade():
    op.drop_constraint('fk_download_transfers_game_uuid_games', 'download_transfers', type_='foreignkey')
    op.drop_index('ix_download_transfers_game_uuid', table_name='download_transfers')
    op.drop_column('download_transfers', 'game_uuid')
