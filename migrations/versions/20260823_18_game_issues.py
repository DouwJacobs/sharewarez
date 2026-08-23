"""Add categorized game issue reports.

Revision ID: 20260823_18
Revises: 20260823_17
"""

from alembic import op
import sqlalchemy as sa


revision = '20260823_18'
down_revision = '20260823_17'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('game_requests', sa.Column('issue_category', sa.String(length=32), nullable=True))


def downgrade():
    op.drop_column('game_requests', 'issue_category')
