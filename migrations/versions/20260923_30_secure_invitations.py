"""secure invitation credentials and add revocation lifecycle

Revision ID: 20260923_30
Revises: 20260922_29
Create Date: 2026-09-23
"""

from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa


revision = '20260923_30'
down_revision = '20260922_29'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {
        column['name']
        for column in sa.inspect(connection).get_columns('invite_tokens')
    }
    if 'token_digest' not in columns:
        op.add_column(
            'invite_tokens',
            sa.Column('token_digest', sa.String(length=64), nullable=True),
        )
    if 'revoked_at' not in columns:
        op.add_column(
            'invite_tokens',
            sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        )
    if 'revoked_by_user_id' not in columns:
        op.add_column(
            'invite_tokens',
            sa.Column('revoked_by_user_id', sa.String(length=36), nullable=True),
        )

    foreign_keys = sa.inspect(connection).get_foreign_keys('invite_tokens')
    has_revocation_foreign_key = any(
        key['constrained_columns'] == ['revoked_by_user_id']
        for key in foreign_keys
    )
    if not has_revocation_foreign_key:
        op.create_foreign_key(
            'fk_invite_tokens_revoked_by_user_id_users',
            'invite_tokens',
            'users',
            ['revoked_by_user_id'],
            ['user_id'],
            ondelete='SET NULL',
        )

    if 'token' in columns:
        invitations = connection.execute(
            sa.text(
                'SELECT id, token FROM invite_tokens '
                'WHERE token_digest IS NULL'
            )
        ).mappings()
        for invitation in invitations:
            digest = hashlib.sha256(
                invitation['token'].encode('utf-8')
            ).hexdigest()
            connection.execute(
                sa.text(
                    'UPDATE invite_tokens SET token_digest = :digest '
                    'WHERE id = :id'
                ),
                {'digest': digest, 'id': invitation['id']},
            )
        op.alter_column('invite_tokens', 'token_digest', nullable=False)

    indexes = {
        index['name']
        for index in sa.inspect(connection).get_indexes('invite_tokens')
    }
    if 'ix_invite_tokens_token_digest' not in indexes:
        op.create_index(
            'ix_invite_tokens_token_digest',
            'invite_tokens',
            ['token_digest'],
            unique=True,
        )
    if 'token' in columns:
        op.drop_column('invite_tokens', 'token')


def downgrade():
    connection = op.get_bind()
    op.add_column('invite_tokens', sa.Column('token', sa.String(length=256), nullable=True))
    connection.execute(sa.text('UPDATE invite_tokens SET token = token_digest'))
    op.alter_column('invite_tokens', 'token', existing_type=sa.String(length=256), nullable=False)
    op.create_unique_constraint('uq_invite_tokens_token', 'invite_tokens', ['token'])
    op.drop_index('ix_invite_tokens_token_digest', table_name='invite_tokens')
    for foreign_key in sa.inspect(connection).get_foreign_keys('invite_tokens'):
        if foreign_key['constrained_columns'] == ['revoked_by_user_id'] and foreign_key.get('name'):
            op.drop_constraint(foreign_key['name'], 'invite_tokens', type_='foreignkey')
            break
    op.drop_column('invite_tokens', 'revoked_by_user_id')
    op.drop_column('invite_tokens', 'revoked_at')
    op.drop_column('invite_tokens', 'token_digest')
