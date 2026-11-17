"""首方产品事件日计数：analytics_daily 表

Revision ID: 0006_analytics_daily
Revises: 0005_trip_last_edited
Create Date: 2026-11-07

只存“哪一天、哪个事件、发生几次”，不含用户、IP、行程或内容；
主键 (day, name) 让多 worker 用 ON CONFLICT 原子自增。
"""
from alembic import op
import sqlalchemy as sa


revision = '0006_analytics_daily'
down_revision = '0005_trip_last_edited'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'analytics_daily',
        sa.Column('day', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('day', 'name'),
    )


def downgrade() -> None:
    op.drop_table('analytics_daily')
