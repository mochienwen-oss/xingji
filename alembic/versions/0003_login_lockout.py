"""登录防爆破：users 连续失败计数、最后失败时间与锁定截止

Revision ID: 0003_login_lockout
Revises: 0002_user_memories
Create Date: 2026-11-07

与 backend/db.py 的 User 三个新列逐列对齐：
- failed_login_count 默认 0（server_default 用 '0'，PostgreSQL 的 integer 不接受空字符串）。
- last_failed_login_at / locked_until 存 UTC ISO 字符串，和 accepted_terms_at 等时间列保持一致。
仅新增列，不改历史行语义；历史行 locked_until 为 NULL 表示未锁定。
"""
from alembic import op
import sqlalchemy as sa


revision = '0003_login_lockout'
down_revision = '0002_user_memories'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('failed_login_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.add_column('users', sa.Column('last_failed_login_at', sa.String(length=32), nullable=True))
    op.add_column('users', sa.Column('locked_until', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'last_failed_login_at')
    op.drop_column('users', 'failed_login_count')
