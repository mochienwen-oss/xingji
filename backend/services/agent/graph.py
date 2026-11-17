"""行程修改图：仅生成预览，行程由用户确认后通过保存接口提交。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from copy import deepcopy

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .. import planning
from ..errors import ServiceError
from . import tools
from .state import AgentState, event


async def understand(state: AgentState) -> dict:
    writer = get_stream_writer()
    now = tools.get_current_time()
    window = tools.trip_window_text(state.get('request') or {})
    tail = f' · {window}' if window else ''
    writer(event('status', phase='understand', text=f'正在理解需求（{now["weekday"]} {now["time"]}{tail}）…'))
    lines = [f'当前北京时间：{now["now"]} {now["weekday"]}（{now["timezone"]}）']
    if window:
        lines.append(f'行程窗口：{window}')
    lines.append(state['context'])
    keywords = await planning.adjustment_keywords('\n'.join(lines), state['days'], state['backlog'])
    return {'context': '\n'.join(lines), 'keywords': keywords}


async def gather(state: AgentState) -> dict:
    writer = get_stream_writer()
    found = dict(state['candidates'])
    keywords = list(state['keywords'])
    # 多个关键词一次并发查：串行往返会把延迟按关键词数线性放大；事件仍按
    # 关键词顺序补发，前端看到的 tool_start/pin/result 顺序不变。
    for keyword in keywords:
        writer(event('tool_start', tool='search_places', keyword=keyword, text=f'正在查找「{keyword}」…'))
    outcomes = await asyncio.gather(*(tools.search_places(state['city'], keyword) for keyword in keywords),
                                    return_exceptions=True)
    for keyword, results in zip(keywords, outcomes):
        if isinstance(results, BaseException):
            if isinstance(results, ServiceError):
                raise results
            raise ServiceError(f'没有找到地点「{keyword}」，请换个说法。', 404) from results
        if not results:
            raise ServiceError(f'没有找到地点「{keyword}」，请换个说法。', 404)
        for place in results[:5]:
            if place['id'] not in found:
                found[place['id']] = place
                writer(event('pin', place=place))
        writer(event('tool_result', tool='search_places', keyword=keyword,
                     count=len(results), text=f'找到 {len(results)} 个候选'))
    return {'found': found, 'candidates': found}


async def plan(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer(event('status', phase='plan', text='正在规划行程调整…'))
    def replier(text: str, reset: bool = False) -> None:
        writer(event('delta', text=text, reset=reset))
    # 图只在「已保存行程的改稿」链路上运行：把行程现场原样交给规划层，
    # 否则会退化成新建预览（行程 ID/版本/长期记忆全部丢失）。
    result = await tools.suggest_edits(state['request'], list(state['candidates'].values()),
                                       state['context'], state['days'], state['backlog'],
                                       on_reply=replier,
                                       mode='trip' if state.get('trip_id') is not None else 'preview',
                                       trip_id=state.get('trip_id'),
                                       version=state.get('version'),
                                       memories=state.get('memories'),
                                       history=state.get('history'))
    writer(event('tool_result', tool='suggest_edits', changed=result['changed'], text=result['reply']))
    if result['changed']:
        for index, day in enumerate(result['days']):
            writer(event('day_done', day=index, stops=[
                {'id': stop['place']['id'], 'name': stop['place']['name']} for stop in day['stops']
            ]))
    return {'suggestion': result, 'reply': result['reply'], 'changed': result['changed']}


async def route(state: AgentState) -> dict:
    if not state['changed']:
        return {'routes_done': False}
    writer = get_stream_writer()
    suggestion = deepcopy(state['suggestion'])
    days = suggestion['days']
    # update_routes 内部已按 AMAP_BATCH_CONCURRENCY 并发；整批一次调用即可，
    # 原来逐段调用会把 N 段变成 N 次串行往返。
    writer(event('status', phase='route', text='正在核对每一段路程…'))
    await tools.update_routes(days, state['transport'], state['city'], state['days'])
    for day_index, day in enumerate(days):
        routes = day.get('routes') or []
        for route_data in routes:
            writer(event('route_seg', day=day_index, origin=route_data['origin'],
                         destination=route_data['destination'], duration=route_data['duration'],
                         distance=route_data.get('distance'), polyline=route_data.get('polyline') or []))
    return {'routes_done': True, 'days': days, 'suggestion': suggestion}


async def respond(state: AgentState) -> dict:
    suggestion = state['suggestion']
    get_stream_writer()(event('done', days=suggestion['days'], backlog=suggestion['backlog'],
                              reply=suggestion['reply'], changed=suggestion['changed']))
    return {}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node('understand', understand)
    graph.add_node('gather', gather)
    graph.add_node('plan', plan)
    graph.add_node('route', route)
    graph.add_node('respond', respond)
    graph.add_edge(START, 'understand')
    graph.add_edge('understand', 'gather')
    graph.add_edge('gather', 'plan')
    graph.add_edge('plan', 'route')
    graph.add_edge('route', 'respond')
    graph.add_edge('respond', END)
    return graph.compile()


async def run_stream(state: AgentState) -> AsyncIterator[dict]:
    graph = build_graph()
    async for mode, chunk in graph.astream(state, stream_mode=['custom', 'updates']):
        if mode == 'custom':
            yield {'events': [chunk]}
        elif chunk:
            for node_output in chunk.values():
                if isinstance(node_output, dict):
                    yield node_output


__all__ = ['build_graph', 'run_stream', 'understand', 'gather', 'plan', 'route', 'respond']
