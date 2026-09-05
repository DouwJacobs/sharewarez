"""Repair fresh-schema search objects and add bounded candidate indexes.

Revision ID: 20260905_25
Revises: 20260904_24
"""
from alembic import op

revision = '20260905_25'
down_revision = '20260904_24'
branch_labels = None
depends_on = None

SEARCH_TABLES = (
    ('games', 'name', 'summary'),
    ('libraries', 'name', 'name'),
    ('users', 'name', 'email'),
    ('game_requests', 'game_name', 'parent_game_name'),
    ('game_issues', 'title', 'description'),
)


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    for table, title, body in SEARCH_TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_search_document ON {table} USING gin (to_tsvector('simple', coalesce({title}, '') || ' ' || coalesce({body}, '')))")
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_name_trgm ON {table} USING gin (lower({title}) gin_trgm_ops)')
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_name_distance ON {table} USING gist (lower({title}) gist_trgm_ops)')


def downgrade():
    # Keep repaired pre-existing search objects available to older releases.
    for table, _, _ in SEARCH_TABLES:
        op.drop_index(f'ix_{table}_name_distance', table_name=table)
