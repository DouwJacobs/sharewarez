"""Establish the Alembic baseline after legacy schema reconciliation.

Revision ID: 20260809_01
Revises:
Create Date: 2026-08-09
"""

revision = '20260809_01'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # InitializationManager creates new schemas from current model metadata and
    # reconciles existing unversioned installations before applying this stamp.
    pass


def downgrade():
    # A baseline stamp never drops application tables or user data.
    pass
