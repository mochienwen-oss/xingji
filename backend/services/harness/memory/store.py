"""全局记忆存取：召回当前生效的记忆，合并模型抽出的候选。

设计要点：
- 同一 (user_id, category, key) 只保留一条生效行；值变了就把旧行标 superseded_at 留档再插入新行，
  唯一索引 uq_user_memories_key 只约束 superseded_at IS NULL 的行。
- 不 commit：事务边界交给调用方（记忆写入和主流程共用一次提交）。
- 记忆是后台增强：脏候选一律跳过不抛，一条非法数据不能拖垮整批。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.db import UserMemory

log = logging.getLogger(__name__)

CATEGORIES = ('preference', 'feedback', 'project', 'resource')
# 简单关键词黑名单：模型偶尔会把密码、证件号当「偏好」记下来，宁可不记。
SENSITIVE_KEYWORDS = ('password', 'passwd', '密码', '身份证', '银行卡', '手机号', '邮箱')
DEFAULT_LIMIT = 8
MAX_LIMIT = 50
MAX_SCOPE = 40
MAX_KEY = 80
MAX_VALUE = 500
MAX_EVIDENCE = 500
DEFAULT_CONFIDENCE = 0.6


def _now() -> datetime:
    """UTC naive：和 DateTime 列一致，避免 SQLite/PostgreSQL 上时区比较出现偏差。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(word in lowered for word in SENSITIVE_KEYWORDS)


def _confidence(raw) -> float | None:
    """缺省 0.6；显式给了但非数字或越界返回 None（= 整条候选非法）。"""
    if raw is None:
        return DEFAULT_CONFIDENCE
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    # NaN 也会被这个区间判断挡掉。
    return value if 0.0 <= value <= 1.0 else None


def _expires_at(raw) -> datetime | None:
    """候选里的过期时间：datetime 或 ISO 字符串；解析不了就当没写（不影响记忆本身）。"""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    return None


def _candidate(raw) -> dict | None:
    """字段校验 + 归一化；任何不合规都返回 None 由调用方跳过。"""
    if not isinstance(raw, dict):
        return None
    category, key, value = raw.get('category'), raw.get('key'), raw.get('value')
    if category not in CATEGORIES or not isinstance(key, str) or not isinstance(value, str):
        return None
    key, value = key.strip(), value.strip()
    if not 1 <= len(key) <= MAX_KEY or not 1 <= len(value) <= MAX_VALUE:
        return None
    evidence = raw.get('evidence')
    evidence = evidence.strip() if isinstance(evidence, str) else ''
    if len(evidence) > MAX_EVIDENCE or _is_sensitive(value):
        return None
    confidence = _confidence(raw.get('confidence'))
    if confidence is None:
        return None
    scope = raw.get('scope')
    return {
        'category': category,
        'scope': scope.strip()[:MAX_SCOPE] if isinstance(scope, str) else '',
        'key': key,
        'value': value,
        'evidence': evidence,
        'confidence': confidence,
        'expires_at': _expires_at(raw.get('expires_at')),
    }


def _limit(raw) -> int:
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(0, min(size, MAX_LIMIT))


def _as_dict(row: UserMemory) -> dict:
    return {
        'id': row.id,
        'category': row.category,
        'scope': row.scope,
        'key': row.key,
        'value': row.value,
        'evidence': row.evidence,
        'confidence': row.confidence,
        'expires_at': row.expires_at,
    }


class MemoryStore:
    """一个 Session 内的记忆读写；commit 由调用方负责。"""

    def __init__(self, db: Session):
        self.db = db

    def list_for_user(self, user_id: int, limit: int = 8) -> list[dict]:
        """当前生效的记忆：未覆盖、未过期，置信度高的在前。"""
        size = _limit(limit)
        if size == 0:
            return []
        now = _now()
        rows = self.db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.superseded_at.is_(None),
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
            .order_by(
                UserMemory.confidence.desc(),
                UserMemory.updated_at.desc(),
                UserMemory.id.desc(),
            )
            .limit(size)
        ).scalars().all()
        return [_as_dict(row) for row in rows]

    def apply(self, user_id: int, candidates: list[dict]) -> int:
        """合并候选，返回实际写入（新增或更新）的条数。"""
        items = [item for item in (_candidate(raw) for raw in candidates or []) if item is not None]
        if not items:
            return 0
        now = _now()
        # 一次取出该用户所有生效记忆，避免每个候选都查一次（候选最多 5 条时也是 N+1）。
        rows = self.db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.superseded_at.is_(None),
            )
        ).scalars().all()
        current = {(row.category, row.key): row for row in rows}
        written = 0
        for item in items:
            if self._write(user_id, item, now, current):
                written += 1
        return written

    def _write(self, user_id: int, item: dict, now: datetime,
               current: dict[tuple[str, str], UserMemory]) -> bool:
        key = (item['category'], item['key'])
        existing = current.get(key)
        if existing is not None and existing.value == item['value']:
            # 值没变：只刷新证据与置信度，同一偏好不会每天长出一行。
            existing.evidence = item['evidence'] or existing.evidence
            existing.confidence = item['confidence']
            existing.scope = item['scope'] or existing.scope
            existing.expires_at = item['expires_at'] or existing.expires_at
            existing.updated_at = now
            return True
        if existing is not None:
            # 值变了：旧行留档，新行生效（唯一索引只约束 superseded_at IS NULL 的行）。
            existing.superseded_at = now
            existing.updated_at = now
        inserted = self._insert(user_id, item, now)
        if inserted is not None:
            current[key] = inserted
        return inserted is not None

    def _insert(self, user_id: int, item: dict, now: datetime) -> UserMemory | None:
        """插入一条生效行；并发下同 key 被抢先写入时静默跳过。

        不用 SAVEPOINT：pysqlite 的遗留事务模式下 RELEASE 会顺带提交外层事务，
        那样会破坏「commit 由调用方负责」的约定。ON CONFLICT DO NOTHING 不发异常、
        不污染 Session，正好对应「冲突跳过不抛」。
        """
        values = {'user_id': user_id, 'created_at': now, 'updated_at': now, **item}
        dialect = self.db.get_bind().dialect.name
        if dialect in ('sqlite', 'postgresql'):
            module = sqlite_insert if dialect == 'sqlite' else pg_insert
            statement = module(UserMemory).values(**values).on_conflict_do_nothing(
                index_elements=['user_id', 'category', 'key'],
                index_where=text('superseded_at IS NULL'),
            ).returning(UserMemory)
            inserted = self.db.execute(statement).scalars().first()
            if inserted is None:
                log.warning('memory apply conflict, skipped key=%s', item['key'])
            return inserted
        row = UserMemory(**values)
        self.db.add(row)
        self.db.flush()
        return row
