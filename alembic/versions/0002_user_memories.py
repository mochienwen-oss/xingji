"""全局记忆：user_memories 表 + users.memory_enabled 开关

Revision ID: 0002_user_memories
Revises: 0001_initial
Create Date: 2026-11-06

与 backend/db.py 的 UserMemory / User.memory_enabled 逐列对齐：
- uq_user_memories_key 是部分唯一索引（WHERE superseded_at IS NULL）：旧版本留档后同 key 还能插新行。
- memory_enabled 的 server_default 用 true：PostgreSQL 的 boolean 列不接受 '1'，SQLite(>=3.23) 也认 true。
"""
from alembic import op
import sqlalchemy as sa


revision = '0002_user_memories'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_memories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('scope', sa.String(length=40), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('superseded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_memories_user', 'user_memories', ['user_id'], unique=False)
    op.create_index(
        'uq_user_memories_key', 'user_memories', ['user_id', 'category', 'key'], unique=True,
        postgresql_where=sa.text('superseded_at IS NULL'),
        sqlite_where=sa.text('superseded_at IS NULL'),
    )
    op.add_column(
        'users',
        sa.Column('memory_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('users', 'memory_enabled')
    op.drop_index('uq_user_memories_key', table_name='user_memories')
    op.drop_index('ix_user_memories_user', table_name='user_memories')
    op.drop_table('user_memories')
