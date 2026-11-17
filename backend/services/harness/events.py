"""Harness 对前端暴露的统一事件。所有事件都是可 JSON 序列化的 dict，kind 为判别字段。"""
from __future__ import annotations

from typing import Any


def event(kind: str, **payload: Any) -> dict:
    return {"kind": kind, **payload}


def phase(name: str, text: str = "") -> dict:
    return event("phase", phase=name, text=text)


def delta(text: str) -> dict:
    return event("assistant_delta", text=text)


def form_patch(patch: dict) -> dict:
    return event("form_patch", patch=patch)


def places(items: list[dict], keyword: str = "") -> dict:
    return event("places", places=items, keyword=keyword)


def plan(data: dict) -> dict:
    return event("plan", plan=data)


def question(text: str) -> dict:
    return event("question", text=text)


def summary_patch(summary: dict, turn_count: int) -> dict:
    return event("summary_patch", summary=summary, turn_count=turn_count)


def done(**payload: Any) -> dict:
    return event("done", **payload)


def error(message: str, *, retryable: bool = True) -> dict:
    return event("error", message=message, retryable=retryable)
