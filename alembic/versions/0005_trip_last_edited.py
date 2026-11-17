"""行程最近编辑人：trips.last_edited_by / last_edited_at

Revision ID: 0005_trip_last_edited
Revises: 0004_trip_reports
Create Date: 2026-11-07

保存冲突时前端要说明线上版本最近由谁保存，只做提示，不用于权限判断。
"""
from alembic import op
import sqlalchemy as sa


revision = '0005_trip_last_edited'
down_revision = '0004_trip_reports'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('last_edited_by', sa.String(length=80), nullable=True))
    op.add_column('trips', sa.Column('last_edited_at', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('trips', 'last_edited_at')
    op.drop_column('trips', 'last_edited_by')
