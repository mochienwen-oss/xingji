"""SSE 通用编排：后台任务 + 队列 + 心跳 + 断开取消。

各业务端点只负责把事件放进队列，传输细节（注释行保活、data 行格式、取消后
等待任务结束）集中在这里，避免四份相同的 while/wait_for/gather 实现继续漂移。

注意：这里不引入任何空闲看门狗或请求超时；客户端断开（生成器被关闭）时
才取消后台任务，与前端「只保留主动 abort」的约定一致。
"""
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi.responses import StreamingResponse

SSE_HEADERS = {'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}


async def event_stream(
    queue: asyncio.Queue,
    producer: Callable[[], Awaitable[None]],
    *,
    heartbeat: float,
    should_cancel: Callable[[], bool] | None = None,
) -> AsyncIterator[str]:
    """启动 producer 并逐条转发队列事件。

    producer 必须在结束时 put(None)；should_cancel 返回 False 时保留任务
    （例如 assistant 流已经发出 done，仍需让后台 task 完成落库）。
    """
    task = asyncio.create_task(producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except asyncio.TimeoutError:
                # 注释行不参与事件解析：模型思考期间定期保活，事件顺序不变。
                yield ': ping\n\n'
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    finally:
        if not task.done() and (should_cancel is None or should_cancel()):
            task.cancel()
        # 取消后等任务真正结束，避免模型请求或落库在后台悬挂。
        await asyncio.gather(task, return_exceptions=True)


def sse_response(
    queue: asyncio.Queue,
    producer: Callable[[], Awaitable[None]],
    *,
    heartbeat: float,
    should_cancel: Callable[[], bool] | None = None,
) -> StreamingResponse:
    """把 event_stream 包装成标准 SSE 响应。"""
    return StreamingResponse(
        event_stream(queue, producer, heartbeat=heartbeat, should_cancel=should_cancel),
        media_type='text/event-stream',
        headers=SSE_HEADERS,
    )
