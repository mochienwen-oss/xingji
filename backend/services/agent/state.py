"""行迹 agent：LangGraph 状态定义。

AgentState 在图的节点之间传递一次行程修改会话的全部上下文；
生命感事件经 get_stream_writer() 自定义通道实时流出（A 类：过程可见），
由 SSE 端点从 run_stream 的 custom 模式信封 {'events': [chunk]} 中消费。
"""
from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # 会话输入
    message: str
    history: list[dict]
    # 行程现场
    trip_id: int
    version: int
    memories: list[dict]
    city: str
    transport: str
    request: dict
    days: list[dict]
    backlog: list[dict]
    candidates: dict[str, dict]
    context: str
    # agent 过程数据
    keywords: list[str]
    found: dict[str, dict]
    suggestion: dict
    routes_done: bool
    reply: str
    changed: bool
    # 终态
    error: str


def event(kind: str, **payload: Any) -> dict:
    """构造一条生命感事件；kind∈status/tool_start/tool_result/day_done/pin/route_seg/done/error。"""
    return {'kind': kind, **payload}
