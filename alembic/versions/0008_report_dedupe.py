"""举报去重：同一用户对同一行程只保留一条待处理举报

Revision ID: 0008_report_dedupe
Revises: 0007_trip_join_code
Create Date: 2026-11-11

历史数据里可能已有同一用户对同一行程的多条 pending 举报（此前只有应用层去重，
并发提交会漏过）。先按 id 保留最早一条，其余改成 dismissed 留档，再建部分唯一索引；
索引只约束 pending 且 reporter_user_id 非空的行，匿名举报和已处理记录不受影响。
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '0008_report_dedupe'
down_revision = '0007_trip_join_code'
branch_labels = None
depends_on = None

_PENDING_REPORTER = "status = 'pending' AND reporter_user_id IS NOT NULL"


def upgrade() -> None:
    bind = op.get_bind()
    reports = sa.table(
        'trip_reports',
        sa.column('id', sa.Integer),
        sa.column('trip_id', sa.Integer),
        sa.column('reporter_user_id', sa.Integer),
        sa.column('status', sa.String),
        sa.column('resolution', sa.String),
        sa.column('resolved_at', sa.String),
    )
    rows = bind.execute(
        sa.select(reports.c.id, reports.c.trip_id, reports.c.reporter_user_id)
        .where(reports.c.status == 'pending', reports.c.reporter_user_id.is_not(None))
        .order_by(reports.c.id)
    ).all()
    seen: set[tuple[int, int]] = set()
    merged_at = datetime.now(timezone.utc).isoformat()
    for report_id, trip_id, reporter_id in rows:
        key = (trip_id, reporter_id)
        if key in seen:
            bind.execute(
                sa.update(reports)
                .where(reports.c.id == report_id)
                .values(status='dismissed', resolution='重复举报（迁移合并）', resolved_at=merged_at)
            )
        else:
            seen.add(key)
    op.create_index(
        'uq_trip_reports_pending_reporter',
        'trip_reports',
        ['trip_id', 'reporter_user_id'],
        unique=True,
        sqlite_where=sa.text(_PENDING_REPORTER),
        postgresql_where=sa.text(_PENDING_REPORTER),
    )
    # 新部分唯一索引以 (trip_id, reporter_user_id) 为前缀，原普通索引不再被任何查询需要。
    op.drop_index('ix_trip_reports_trip_reporter', table_name='trip_reports')


def downgrade() -> None:
    op.create_index('ix_trip_reports_trip_reporter', 'trip_reports', ['trip_id', 'reporter_user_id'])
    op.drop_index('uq_trip_reports_pending_reporter', table_name='trip_reports')
