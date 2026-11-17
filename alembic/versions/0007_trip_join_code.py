"""行程分享码：trips.join_code 与唯一索引

Revision ID: 0007_trip_join_code
Revises: 0006_analytics_daily
Create Date: 2026-11-08

8 位大写字母+数字分享码，供朋友输入加入协作；空值表示未启用分享码。
唯一索引在 SQLite/PostgreSQL 都允许多个 NULL，未启用分享码的历史行程不受影响。
"""
from alembic import op
import sqlalchemy as sa


revision = '0007_trip_join_code'
down_revision = '0006_analytics_daily'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('join_code', sa.String(length=8), nullable=True))
    op.create_index('ix_trips_join_code', 'trips', ['join_code'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_trips_join_code', table_name='trips')
    op.drop_column('trips', 'join_code')
