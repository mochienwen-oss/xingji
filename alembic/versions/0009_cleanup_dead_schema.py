"""清理无人使用/重复的 schema：登录锁定列、冗余索引、行程版本默认值

Revision ID: 0009_cleanup_dead_schema
Revises: 0008_report_dedupe
Create Date: 2026-11-11

- users.failed_login_count / last_failed_login_at / locked_until 自 0003 引入后，
  登录防爆破已改为进程内 (username, IP) 计数，应用不再读写这三列，删除以免误导。
- ix_user_memories_user 被部分唯一索引 uq_user_memories_key（user_id 前缀）覆盖，
  所有按用户查询都走后者，删除冗余索引。
- trips.version / is_public 之前只有 Python 侧 default，裸 SQL 插入会因 NOT NULL 失败；
  补 server_default '0'（SQLite 需重建表以修改列默认值）。
"""
from alembic import op
import sqlalchemy as sa


revision = '0009_cleanup_dead_schema'
down_revision = '0008_report_dedupe'
branch_labels = None
depends_on = None

_DEAD_USER_COLUMNS = (
    ('failed_login_count', sa.Integer(), False),
    ('last_failed_login_at', sa.String(length=32), True),
    ('locked_until', sa.String(length=32), True),
)


def _sqlite() -> bool:
    return op.get_bind().dialect.name == 'sqlite'


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        # users 上还有部分唯一索引 ix_users_email，batch recreate 会丢掉 WHERE 子句，
        # 因此这里直接用 SQLite 3.35+ 的 DROP COLUMN，保留索引与数据。
        for name, _type, _nullable in _DEAD_USER_COLUMNS:
            op.execute(f'ALTER TABLE users DROP COLUMN {name}')
    else:
        for name, _type, _nullable in _DEAD_USER_COLUMNS:
            op.drop_column('users', name)

    op.drop_index('ix_user_memories_user', table_name='user_memories')

    if dialect == 'sqlite':
        # SQLite 不支持 ALTER COLUMN，用 batch 重建 trips；显式带上 sqlite_autoincrement，
        # 避免重建后 id 变成可复用（过期清理删掉最大 id 后会被新行程继承）。
        with op.batch_alter_table(
            'trips', recreate='always', table_kwargs={'sqlite_autoincrement': True}
        ) as batch:
            batch.alter_column('version', existing_type=sa.Integer(), nullable=False,
                               server_default=sa.text('0'))
            batch.alter_column('is_public', existing_type=sa.Integer(), nullable=False,
                               server_default=sa.text('0'))
    else:
        op.alter_column('trips', 'version', existing_type=sa.Integer(), nullable=False,
                        server_default=sa.text('0'))
        op.alter_column('trips', 'is_public', existing_type=sa.Integer(), nullable=False,
                        server_default=sa.text('0'))


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        with op.batch_alter_table(
            'trips', recreate='always', table_kwargs={'sqlite_autoincrement': True}
        ) as batch:
            batch.alter_column('version', existing_type=sa.Integer(), nullable=False,
                               server_default=None)
            batch.alter_column('is_public', existing_type=sa.Integer(), nullable=False,
                               server_default=None)
    else:
        op.alter_column('trips', 'version', existing_type=sa.Integer(), nullable=False,
                        server_default=None)
        op.alter_column('trips', 'is_public', existing_type=sa.Integer(), nullable=False,
                        server_default=None)

    op.create_index('ix_user_memories_user', 'user_memories', ['user_id'])
    for name, type_, nullable in _DEAD_USER_COLUMNS:
        # 老行必须有默认值才能补 NOT NULL 列；0003 当初也是这么建的。
        default = sa.text('0') if name == 'failed_login_count' else None
        op.add_column('users', sa.Column(name, type_, nullable=nullable, server_default=default))
