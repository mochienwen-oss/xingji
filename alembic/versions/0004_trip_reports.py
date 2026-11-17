"""UGC 举报：trip_reports 表

Revision ID: 0004_trip_reports
Revises: 0003_login_lockout
Create Date: 2026-11-07

举报记录要独立于行程生命周期：行程被删除/清理后仍保留审计线索，
因此 trip_id 与 reporter_user_id 有意不设外键。
"""
from alembic import op
import sqlalchemy as sa


revision = '0004_trip_reports'
down_revision = '0003_login_lockout'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'trip_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('trip_title', sa.String(length=120), nullable=True),
        sa.Column('trip_city', sa.String(length=80), nullable=False),
        sa.Column('reporter_user_id', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(length=20), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.String(length=32), nullable=False),
        sa.Column('resolved_at', sa.String(length=32), nullable=True),
        sa.Column('resolution', sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_reports_trip_reporter', 'trip_reports', ['trip_id', 'reporter_user_id'])
    op.create_index('ix_trip_reports_status_created', 'trip_reports', ['status', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_trip_reports_status_created', table_name='trip_reports')
    op.drop_index('ix_trip_reports_trip_reporter', table_name='trip_reports')
    op.drop_table('trip_reports')
