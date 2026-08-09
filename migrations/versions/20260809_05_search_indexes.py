"""Add indexed full-text and fuzzy search support.

Revision ID: 20260809_05
Revises: 20260809_04
"""

from alembic import op

revision = '20260809_05'
down_revision = '20260809_04'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.execute("CREATE INDEX ix_games_search_document ON games USING gin (to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(summary, '')))")
    op.execute('CREATE INDEX ix_games_name_trgm ON games USING gin (lower(name) gin_trgm_ops)')
    op.execute('CREATE INDEX ix_libraries_name_trgm ON libraries USING gin (lower(name) gin_trgm_ops)')
    op.execute('CREATE INDEX ix_users_name_trgm ON users USING gin (lower(name) gin_trgm_ops)')
    op.execute('CREATE INDEX ix_game_requests_name_trgm ON game_requests USING gin (lower(game_name) gin_trgm_ops)')


def downgrade():
    op.drop_index('ix_game_requests_name_trgm', table_name='game_requests')
    op.drop_index('ix_users_name_trgm', table_name='users')
    op.drop_index('ix_libraries_name_trgm', table_name='libraries')
    op.drop_index('ix_games_name_trgm', table_name='games')
    op.drop_index('ix_games_search_document', table_name='games')
