"""initial schema：8 张业务表（users/trips/协作/邀请/分享/预算/支出）

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-06

与 backend/db.py 里的 SQLAlchemy 模型逐列对齐：类型、可空性、默认值、索引名。
注意：
- 不含 SQLite 专有的自增选项（PostgreSQL 用 IDENTITY/序列）。
- users.email 用部分唯一索引（WHERE email IS NOT NULL）：未填邮箱的行不参与唯一性。
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('pending_email', sa.String(length=254), nullable=True),
        sa.Column('email_verified_at', sa.String(length=32), nullable=True),
        sa.Column('accepted_terms_at', sa.String(length=32), nullable=True),
        sa.Column('session_version', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
        sa.Column('session_nonce', sa.String(length=64), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    # 邮箱唯一的条件版本：SQLite 与 PostgreSQL 都支持部分唯一索引。
    op.create_index(
        'ix_users_email', 'users', ['email'], unique=True,
        postgresql_where=sa.text('email IS NOT NULL'),
        sqlite_where=sa.text('email IS NOT NULL'),
    )

    op.create_table(
        'account_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('created_at', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.String(length=32), nullable=False),
        sa.Column('used_at', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_account_tokens_user_id', 'account_tokens', ['user_id'], unique=False)
    op.create_index('ix_account_tokens_token_hash', 'account_tokens', ['token_hash'], unique=True)

    op.create_table(
        'trips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('city', sa.String(length=80), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=True),
        sa.Column('deleted_at', sa.String(length=32), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('is_public', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trips_user_id', 'trips', ['user_id'], unique=False)
    op.create_index('ix_trips_user_deleted', 'trips', ['user_id', 'deleted_at'], unique=False)
    op.create_index('ix_trips_public_deleted', 'trips', ['is_public', 'deleted_at'], unique=False)

    op.create_table(
        'trip_collaborators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trip_id', 'user_id'),
    )
    op.create_index('ix_trip_collaborators_trip_id', 'trip_collaborators', ['trip_id'], unique=False)
    op.create_index('ix_trip_collaborators_user_id', 'trip_collaborators', ['user_id'], unique=False)

    op.create_table(
        'trip_invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_invites_trip_id', 'trip_invites', ['trip_id'], unique=False)
    op.create_index('ix_trip_invites_token_hash', 'trip_invites', ['token_hash'], unique=True)

    op.create_table(
        'share_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('revoked_at', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_share_links_trip_id', 'share_links', ['trip_id'], unique=False)
    op.create_index('ix_share_links_token_hash', 'share_links', ['token_hash'], unique=True)

    op.create_table(
        'trip_budgets',
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
        sa.PrimaryKeyConstraint('trip_id'),
    )

    op.create_table(
        'expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('expense_date', sa.String(length=10), nullable=False),
        sa.Column('place_id', sa.String(length=100), nullable=True),
        sa.Column('note', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_expenses_trip_id', 'expenses', ['trip_id'], unique=False)


def downgrade() -> None:
    op.drop_table('expenses')
    op.drop_table('trip_budgets')
    op.drop_table('share_links')
    op.drop_table('trip_invites')
    op.drop_table('trip_collaborators')
    op.drop_table('trips')
    op.drop_table('account_tokens')
    op.drop_table('users')
