"""prefer the Game Library local metadata filename

Revision ID: 20260925_32
Revises: 20260924_31
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa


revision = '20260925_32'
down_revision = '20260924_31'
branch_labels = None
depends_on = None


def upgrade():
    # Existing row values are intentionally preserved for compatibility. This
    # changes only the database default used by future rows.
    op.alter_column(
        'global_settings',
        'local_metadata_filename',
        existing_type=sa.String(length=50),
        server_default='gamelibrary.json',
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'global_settings',
        'local_metadata_filename',
        existing_type=sa.String(length=50),
        server_default='sharewarez.json',
        existing_nullable=True,
    )
