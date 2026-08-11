"""Add admin-managed system email templates.

Revision ID: 20260811_07
Revises: 20260809_06
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_07'
down_revision = '20260809_06'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_email_templates',
        sa.Column('template_key', sa.String(length=64), nullable=False),
        sa.Column('subject_template', sa.String(length=255), nullable=False),
        sa.Column('html_template', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('template_key'),
    )


def downgrade():
    op.drop_table('system_email_templates')
