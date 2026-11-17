"""9 段式上下文压缩。

触发条件（任一）：估算 token 超过上下文预算 60%、轮次超过 8、消息超过 12 条、切换城市。
压缩后保留最近 4 条原文；摘要固定 9 个字段，其中 all_user_messages 必须保留所有用户原文。
模型压缩失败时走确定性降级，绝不让规划因为压缩而中断。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..env import env_float, env_int
from ..llm import model_json
from .prompts import registry

log = logging.getLogger("uvicorn.error")

SUMMARY_FIELDS = (
    "core_request",
    "key_concepts",
    "data_and_interfaces",
    "errors_and_fixes",
    "resolution_process",
    "all_user_messages",
    "pending_tasks",
    "current_work",
    "next_action",
)
KEEP_RECENT = 4
CONTEXT_WINDOW_TOKENS = env_int("HARNESS_CONTEXT_WINDOW", 64000, minimum=1000)
COMPACT_AT_RATIO = env_float("HARNESS_COMPACT_RATIO", 0.6, minimum=0.05)
COMPACT_AT_TURNS = env_int("HARNESS_COMPACT_TURNS", 8, minimum=1)
COMPACT_AT_MESSAGES = env_int("HARNESS_COMPACT_MESSAGES", 12, minimum=1)
MAX_HISTORY_MESSAGES = env_int("HARNESS_MAX_HISTORY", 24, minimum=1)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + max(0, (len(text) - cjk) // 4)


def messages_tokens(messages: list[dict]) -> int:
    return sum(estimate_tokens(str(m.get("content", ""))) for m in messages) + len(messages) * 4


def needs_compaction(
    messages: list[dict],
    *,
    turn_count: int = 0,
    city_changed: bool = False,
    summary: dict | None = None,
) -> bool:
    if city_changed:
        return True
    # 只在每 N 轮的边界压缩一次，避免第 8 轮之后每轮都重新摘要。
    if turn_count > 0 and turn_count % COMPACT_AT_TURNS == 0:
        return True
    # 已经有摘要时，消息条数不会再回落到阈值以下；只靠每 N 轮 / token / 换城
    # 触发，否则第 7 轮之后每一轮都会重新摘要一次。
    if not summary and len(messages) > COMPACT_AT_MESSAGES:
        return True
    return messages_tokens(messages) > int(CONTEXT_WINDOW_TOKENS * COMPACT_AT_RATIO)


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_summary(raw: dict | None, fallback_messages: list[dict], previous: dict | None = None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    summary = {
        "core_request": _text(raw.get("core_request")),
        "key_concepts": _text(raw.get("key_concepts")),
        "data_and_interfaces": _text(raw.get("data_and_interfaces")),
        "errors_and_fixes": _text(raw.get("errors_and_fixes")),
        "resolution_process": _text(raw.get("resolution_process")),
        "all_user_messages": _list(raw.get("all_user_messages")),
        "pending_tasks": [str(x) for x in _list(raw.get("pending_tasks")) if str(x).strip()],
        "current_work": _text(raw.get("current_work")),
        "next_action": _text(raw.get("next_action")),
    }
    expected: list[str] = []
    if previous:
        expected.extend(str(x) for x in _list(previous.get("all_user_messages")) if str(x).strip())
    expected.extend(str(m.get("content", "")).strip() for m in fallback_messages if m.get("role") == "user")
    seen = {str(x).strip() for x in summary["all_user_messages"]}
    for item in expected:
        if item and item not in seen:
            summary["all_user_messages"].append(item)
            seen.add(item)
    return summary


def fallback_summary(messages: list[dict], previous: dict | None = None, reason: str = "") -> dict:
    user_messages = [str(m.get("content", "")).strip() for m in messages if m.get("role") == "user"]
    last_assistant = next((str(m.get("content", "")).strip() for m in reversed(messages) if m.get("role") == "assistant"), "")
    core = user_messages[-1] if user_messages else (previous or {}).get("core_request", "")
    return normalize_summary(
        {
            "core_request": core,
            "key_concepts": (previous or {}).get("key_concepts", ""),
            "data_and_interfaces": (previous or {}).get("data_and_interfaces", ""),
            "errors_and_fixes": reason or (previous or {}).get("errors_and_fixes", ""),
            "resolution_process": (previous or {}).get("resolution_process", ""),
            "all_user_messages": user_messages,
            "pending_tasks": (previous or {}).get("pending_tasks", []),
            "current_work": last_assistant or (previous or {}).get("current_work", ""),
            "next_action": "继续根据用户最新一句话推进：%s" % (core[:120] if core else "等待用户补充"),
        },
        messages,
        previous,
    )


def summary_to_text(summary: dict | None) -> str:
    if not summary:
        return ""
    lines = []
    labels = {
        "core_request": "核心请求",
        "key_concepts": "关键概念",
        "data_and_interfaces": "关键数据与接口",
        "errors_and_fixes": "错误与修复",
        "resolution_process": "解决过程",
        "all_user_messages": "所有用户消息原文",
        "pending_tasks": "待办",
        "current_work": "当前工作",
        "next_action": "下一步",
    }
    for field in SUMMARY_FIELDS:
        value = summary.get(field)
        if isinstance(value, list):
            if not value:
                continue
            value = "\n".join(f"- {item}" for item in value)
        if not value:
            continue
        lines.append(f"## {labels[field]}\n{value}")
    return "\n".join(lines)


async def compact(messages: list[dict], *, previous: dict | None = None, dynamic: dict | None = None) -> dict:
    """调用模型生成 9 段摘要；任何异常都返回确定性摘要。"""
    if not messages:
        return previous or normalize_summary({}, [])
    conversation = [
        {"role": m.get("role"), "content": str(m.get("content", ""))[:2000]}
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]
    payload = {
        "旧摘要": previous or None,
        "待压缩对话": conversation,
        "当前状态": dynamic or None,
        "当前时间": datetime.now(timezone.utc).isoformat(),
    }
    prompt_messages = registry.build(
        "context_compress",
        dynamic=payload,
        history=[],
        with_example=True,
    )
    try:
        raw = await model_json(prompt_messages, 2000)
        if not isinstance(raw, dict):
            raise ValueError("summary shape")
        return normalize_summary(raw, messages, previous)
    except Exception as exc:  # noqa: BLE001 - 压缩失败必须降级，不能打断主流程
        log.warning("context compaction fallback: %s", type(exc).__name__)
        return fallback_summary(messages, previous, reason=f"压缩降级：{type(exc).__name__}")


def trim_history(messages: list[dict], limit: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    cleaned = [
        {"role": m["role"], "content": str(m["content"])[:2000]}
        for m in messages
        if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()
    ]
    return cleaned[-limit:]
