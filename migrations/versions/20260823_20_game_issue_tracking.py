"""Add standalone game issue tracking and comments.

Revision ID: 20260823_20
Revises: 20260823_19
"""

from alembic import op
import sqlalchemy as sa


revision = '20260823_20'
down_revision = '20260823_19'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_issues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game_uuid', sa.String(length=36), nullable=False),
        sa.Column('reporter_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='open'),
        sa.Column('handled_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['game_uuid'], ['games.uuid'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['handled_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_game_issues_game_uuid', 'game_issues', ['game_uuid'])
    op.create_index('ix_game_issues_reporter_id', 'game_issues', ['reporter_id'])
    op.create_index('ix_game_issues_category', 'game_issues', ['category'])
    op.create_index('ix_game_issues_status', 'game_issues', ['status'])
    op.create_index('ix_game_issues_handled_by_user_id', 'game_issues', ['handled_by_user_id'])
    op.create_index('ix_game_issues_created_at', 'game_issues', ['created_at'])
    op.create_index('ix_game_issues_updated_at', 'game_issues', ['updated_at'])

    op.create_table(
        'game_issue_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('issue_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='comment'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['issue_id'], ['game_issues.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_game_issue_comments_issue_id', 'game_issue_comments', ['issue_id'])
    op.create_index('ix_game_issue_comments_author_id', 'game_issue_comments', ['author_id'])
    op.create_index('ix_game_issue_comments_created_at', 'game_issue_comments', ['created_at'])


def downgrade():
    op.drop_index('ix_game_issue_comments_created_at', table_name='game_issue_comments')
    op.drop_index('ix_game_issue_comments_author_id', table_name='game_issue_comments')
    op.drop_index('ix_game_issue_comments_issue_id', table_name='game_issue_comments')
    op.drop_table('game_issue_comments')
    op.drop_index('ix_game_issues_updated_at', table_name='game_issues')
    op.drop_index('ix_game_issues_created_at', table_name='game_issues')
    op.drop_index('ix_game_issues_handled_by_user_id', table_name='game_issues')
    op.drop_index('ix_game_issues_status', table_name='game_issues')
    op.drop_index('ix_game_issues_category', table_name='game_issues')
    op.drop_index('ix_game_issues_reporter_id', table_name='game_issues')
    op.drop_index('ix_game_issues_game_uuid', table_name='game_issues')
    op.drop_table('game_issues')
