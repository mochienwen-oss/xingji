"""行迹 agent 工具层。

每个工具都是模型可调用的原子能力：
- get_current_time：时间认知（Asia/Shanghai 本地时间 + 星期）。
- trip_window_text：行程窗口（纯日期差，供状态行播报与 context 注入）。
- search_places：高德地点搜索（新增候选）。
- suggest_edits：LLM 生成行程修改建议并本地应用校验。
- update_routes：按交通方式补齐路线（含 polyline，供前端逐段绘制）。

工具自身不 emit 事件；节点在调用前后 emit tool_start/tool_result，
让前端能实时呈现「正在做什么、做到了哪一步」。
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from .. import amap, planning

CN_WEEKDAYS = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
CN_TZ = timezone(timedelta(hours=8))


def get_current_time() -> dict:
    """获取当前中国本地时间。模型由此获得时间认知：判断营业状态、行程当天、早晚。"""
    local = datetime.now(CN_TZ)
    return {
        'now': local.strftime('%Y-%m-%d %H:%M'),
        'date': local.strftime('%Y-%m-%d'),
        'time': local.strftime('%H:%M'),
        'weekday': CN_WEEKDAYS[local.weekday()],
        'timezone': 'Asia/Shanghai (UTC+8)',
    }


def trip_window_text(request: dict) -> str:
    """按出发日期计算行程窗口（纯日期差，供时间认知播报；无法解析时返回空串）。

    返回形如「行程 2026-11-08 启程（还有 3 天），共 3 天」「今天是行程第 2/3 天」
    「行程已于 2026-11-10 结束」的短句；写入 context 供模型做时间相关的判断。
    """
    start = str((request or {}).get('start_date') or '').strip()
    total = int((request or {}).get('days') or 0)
    if not start or total <= 0:
        return ''
    try:
        first = datetime.strptime(start, '%Y-%m-%d').date()
    except ValueError:
        return ''
    # 极端未来日期（如 9999-12-31）加天数会溢出 date，钳制到 date.max
    last = min(first + timedelta(days=total - 1), date.max)
    today = datetime.now(CN_TZ).date()
    if today < first:
        return f'行程 {start} 启程（还有 {(first - today).days} 天），共 {total} 天'
    if today > last:
        return f'行程已于 {last.isoformat()} 结束'
    return f'今天是行程第 {(today - first).days + 1}/{total} 天'


async def search_places(city: str, keyword: str) -> list[dict]:
    """按城市+关键词搜索高德地点，返回候选列表（失败时抛 ServiceError，由节点转 error 事件）。"""
    return await amap.search_places(city, keyword)


async def suggest_edits(request: dict, candidates: list[dict], context: str,
                        days: list[dict], backlog: list[dict], on_reply=None, *,
                        mode: str = 'preview', trip_id: int | None = None,
                        version: int | None = None, memories: list[dict] | None = None,
                        history: list[dict] | None = None) -> dict:
    """生成行程修改建议并本地应用校验，返回 {days,backlog,reply,changed}。

    已保存行程必须带 mode='trip'、行程 ID/版本与长期记忆：规划层据此选择
    trip_revise 场景并注入现场，否则会按「新建行程预览」的契约生成。
    """
    return await planning.suggest_edits(request, candidates, context, days, backlog,
                                        on_reply=on_reply, mode=mode, trip_id=trip_id,
                                        version=version, memories=memories, history=history)


async def update_routes(days: list[dict], mode: str, city: str,
                        old_days: list[dict] | None = None) -> None:
    """按交通方式补齐每天相邻站点之间的路线（逐段 polyline）。"""
    await amap.update_routes(days, mode, city, old_days)
