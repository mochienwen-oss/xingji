"""全局记忆抽取：从最近对话里提炼可长期复用的候选记忆。

只做「对话 -> 候选列表」这一步，不碰数据库、不做触发节流（由 orchestrator 每 N 轮调用）。
记忆是后台增强：模型或结构出错一律退化成 []，绝不让主流程失败。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.services.llm import ModelOutputError, model_json

log = logging.getLogger(__name__)

MAX_CANDIDATES = 5
MAX_MESSAGES = 12
MAX_EXISTING = 20
MAX_TOKENS = 1200
CATEGORIES = ('preference', 'feedback', 'project', 'resource')
MAX_SCOPE = 40
MAX_KEY = 80
MAX_VALUE = 500
MAX_EVIDENCE = 500
DEFAULT_CONFIDENCE = 0.6
EXTRACT_ATTEMPTS = 2

# backend/services/harness/memory/extractor.py -> backend/prompts/scenarios/memory_extract.md
PROMPT_PATH = Path(__file__).resolve().parents[3] / 'prompts' / 'scenarios' / 'memory_extract.md'

# 场景 prompt（backend/prompts/scenarios/memory_extract.md）缺失或为空时用同义内置版本兜底。
FALLBACK_PROMPT = (
    '你是旅行助手的记忆整理器。阅读最近对话，提炼值得跨会话长期记住的用户信息。'
    '只输出 JSON：{"memories": [{"category": "preference|feedback|project|resource", '
    '"scope": "适用城市或主题，可空", "key": "简短稳定的标识", '
    '"value": "一句话结论", "evidence": "对话里的依据", "confidence": 0.6}]}。'
    '最多 5 条；只记录用户明确表达、以后还有用的信息；不记录密码、证件号、银行卡、手机号、邮箱等敏感信息；'
    '没有可记的内容就输出 {"memories": []}。'
)


def load_prompt() -> str:
    """读取场景 prompt；文件不存在或为空时回退到内置版本。"""
    try:
        text = PROMPT_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        return FALLBACK_PROMPT
    return text or FALLBACK_PROMPT


def _confidence(raw) -> float | None:
    """缺省 0.6；显式给了但非数字或越界返回 None（= 整条候选非法）。"""
    if raw is None:
        return DEFAULT_CONFIDENCE
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if 0.0 <= value <= 1.0 else None


def _candidate(raw) -> dict | None:
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
    if len(evidence) > MAX_EVIDENCE:
        return None
    confidence = _confidence(raw.get('confidence'))
    if confidence is None:
        return None
    scope = raw.get('scope')
    candidate = {
        'category': category,
        'scope': scope.strip()[:MAX_SCOPE] if isinstance(scope, str) else '',
        'key': key,
        'value': value,
        'evidence': evidence,
        'confidence': confidence,
    }
    expires_at = raw.get('expires_at')
    if isinstance(expires_at, str) and expires_at.strip():
        candidate['expires_at'] = expires_at.strip()
    return candidate


def _clean(raw) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    items = raw.get('memories')
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items:
        candidate = _candidate(item)
        if candidate is None:
            continue
        cleaned.append(candidate)
        if len(cleaned) >= MAX_CANDIDATES:
            break
    return cleaned


async def extract_memories(messages: list[dict], existing: list[dict], summary: dict | None) -> list[dict]:
    """返回至多 5 条清洗后的候选；失败时返回 []（这轮没有新记忆）。"""
    payload = {
        '已有记忆': list(existing or [])[-MAX_EXISTING:],
        '对话摘要': summary or {},
        '最近对话': list(messages or [])[-MAX_MESSAGES:],
    }
    prompt = [
        {'role': 'system', 'content': load_prompt()},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    for attempt in range(EXTRACT_ATTEMPTS):
        try:
            raw = await model_json(prompt, max_tokens=MAX_TOKENS)
            return _clean(raw)
        except ModelOutputError as exc:
            # 上游偶发返回空 choices / 截断；重试一次通常能拿到合法 JSON。
            if attempt + 1 >= EXTRACT_ATTEMPTS:
                log.warning('memory extract failed: %s: %s', type(exc).__name__, exc)
                return []
            log.info('memory extract retrying after %s', type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - 记忆是后台增强，任何失败都只丢这一轮
            log.warning('memory extract failed: %s: %s', type(exc).__name__, exc)
            return []
    return []
