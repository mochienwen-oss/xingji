"""行程实时协同：WebSocket 房间、在线 presence 与版本 watcher。

同一进程内的连接共享 _rooms；presence 另外通过 Redis ZSET 共享，配置
REDIS_URL 后多个 worker 能看到彼此的用户，未配置时完全回退到本地房间，
行为与单进程版本一致。版本 watcher 仍由各进程按 LIVE_POLL_SECONDS 轮询：
它只读取数据库并在本进程广播，不是需要跨进程共享的状态。

Redis key 设计：
- xingji:live:presence:{trip_id}：ZSET，member 是连接身份 JSON，score 是心跳时间；
  超过 PRESENCE_TTL 未心跳的连接在读取时被裁掉，进程崩溃不会永久留下幽灵成员。
- xingji:live:events：PUB/SUB 频道，广播 presence 变化；消息带 origin 供发布者
  跳过自己的回声，避免本进程重复广播。
"""
import asyncio
import json
import logging
import os
import time
import uuid

from sqlalchemy import select

from .. import db as app_db
from ..db import Trip, User
from . import redis_bus

log = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 1.5
PRESENCE_TTL_SECONDS = 45.0
_PRESENCE_KEY = 'xingji:live:presence:{trip_id}'
_EVENTS_CHANNEL = 'xingji:live:events'
_PROCESS_ID = uuid.uuid4().hex


def _poll_seconds() -> float:
    """LIVE_POLL_SECONDS 控制版本轮询间隔；非法值回落到默认值，避免 watcher 空转或卡死。"""
    raw = os.getenv('LIVE_POLL_SECONDS', '').strip()
    if not raw:
        return DEFAULT_POLL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_POLL_SECONDS
    return value if value > 0 else DEFAULT_POLL_SECONDS

# 模块级常量：测试可 monkeypatch 成很小的值来验证 watcher 推送。
LIVE_POLL_SECONDS = _poll_seconds()

class Connection:
    """一条实时连接：带上用户身份与发送锁，广播时消息不会在字节层面交错。"""

    def __init__(self, websocket, user_id: int, username: str, token: str = '') -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.username = username
        # 握手时的原始会话令牌：心跳复核用，登出/撤销会话后 session_version 变化即可判定失效。
        self.token = token
        self.lock = asyncio.Lock()
        self.connection_id = uuid.uuid4().hex
        self.member = json.dumps(
            {'connection_id': self.connection_id, 'user_id': user_id, 'username': username},
            ensure_ascii=False, separators=(',', ':'),
        )

class Room:
    """一个行程的在线房间：连接列表 + 最近一次广播出去的版本号。"""

    def __init__(self, trip_id: int, version: int) -> None:
        self.trip_id = trip_id
        self.version = version
        self.connections: list[Connection] = []
        self.watcher: asyncio.Task | None = None

_rooms: dict[int, Room] = {}
# 跨 worker 的在线名单缓存：由 PUB/SUB 与每次 join/leave 时的 ZSET 读取维护。
_shared_presence: dict[int, list[dict]] = {}
_listener_task: asyncio.Task | None = None
_listener_lock = asyncio.Lock()

def _dedupe(items: list[dict]) -> list[dict]:
    seen: dict[int, str] = {}
    for item in items:
        user_id = item.get('user_id')
        if isinstance(user_id, int):
            seen.setdefault(user_id, str(item.get('username') or ''))
    return [{'user_id': user_id, 'username': username} for user_id, username in seen.items()]

def presence(room: Room) -> list[dict]:
    """按 user_id 去重：同一个人开多个标签页也只算一位在线规划者。

    配置 Redis 后优先返回共享缓存（含其它 worker 上的连接）；缓存尚未建立时
    回退到本地房间，保证刚启动/Redis 故障时仍有可用数据。
    """
    shared = _shared_presence.get(room.trip_id)
    if shared is not None:
        return [dict(item) for item in shared]
    return _dedupe([{'user_id': c.user_id, 'username': c.username} for c in room.connections])

def online_count(trip_id: int) -> int:
    """在线规划人数：同一用户开多个标签页只算 1 人，没有房间就是 0。

    同步读取本地房间/共享缓存，不碰 DB，可在普通请求处理里随时调用。
    """
    shared = _shared_presence.get(trip_id)
    if shared is not None:
        return len(shared)
    room = _rooms.get(trip_id)
    return len(_dedupe([{'user_id': c.user_id, 'username': c.username} for c in room.connections])) if room else 0

async def online_count_shared(trip_id: int) -> int:
    """读取 Redis 的实时在线人数；未启用 Redis 时等价于 online_count。"""
    client = redis_bus.client()
    if client is None:
        return online_count(trip_id)
    try:
        entries = await _redis_presence(trip_id)
        _shared_presence[trip_id] = entries
        return len(entries)
    except Exception as exc:  # noqa: BLE001 - 列表接口不能因 Redis 抖动而 500
        log.warning('读取 Redis 在线名单失败（trip_id=%s）：%s', trip_id, type(exc).__name__)
        redis_bus.mark_failure()
        _shared_presence.pop(trip_id, None)
        return online_count(trip_id)

async def send(connection: Connection, payload: dict) -> bool:
    """给单条连接发消息：失败只影响自己，返回 False 让调用方决定是否移除。"""
    try:
        async with connection.lock:
            await connection.websocket.send_json(payload)
        return True
    except Exception as exc:  # noqa: BLE001 —— 断网/对端关闭都算发送失败，广播不能因此中断
        log.debug('实时协同发送失败（user_id=%s）：%s', connection.user_id, type(exc).__name__)
        return False

async def broadcast(room: Room, payload: dict) -> None:
    """广播给房间内所有连接：逐个发送，单个连接异常不影响其它人。"""
    for connection in list(room.connections):
        await send(connection, payload)

async def _redis_presence(trip_id: int) -> list[dict]:
    client = redis_bus.client()
    if client is None:
        return []
    key = _PRESENCE_KEY.format(trip_id=trip_id)
    now = time.time()
    await client.zremrangebyscore(key, '-inf', now - PRESENCE_TTL_SECONDS)
    rows = await client.zrangebyscore(key, now - PRESENCE_TTL_SECONDS, '+inf')
    items: list[dict] = []
    for raw in rows:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            items.append({'user_id': value.get('user_id'), 'username': value.get('username') or ''})
    return _dedupe(items)

async def _redis_touch(connection: Connection, trip_id: int) -> None:
    client = redis_bus.client()
    if client is None:
        return
    key = _PRESENCE_KEY.format(trip_id=trip_id)
    await client.zadd(key, {connection.member: time.time()})
    await client.expire(key, 120)

async def _redis_leave(connection: Connection, trip_id: int) -> None:
    client = redis_bus.client()
    if client is None:
        return
    await client.zrem(_PRESENCE_KEY.format(trip_id=trip_id), connection.member)

async def _publish(payload: dict) -> None:
    client = redis_bus.client()
    if client is None:
        return
    message = dict(payload, origin=_PROCESS_ID)
    await client.publish(_EVENTS_CHANNEL, json.dumps(message, ensure_ascii=False))

async def _listen_once() -> None:
    client = redis_bus.client()
    if client is None:
        return
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(_EVENTS_CHANNEL)
        async for message in pubsub.listen():
            if message.get('type') != 'message':
                continue
            try:
                event = json.loads(message.get('data') or '')
            except (TypeError, ValueError):
                continue
            if not isinstance(event, dict) or event.get('origin') == _PROCESS_ID:
                continue
            if event.get('type') != 'presence':
                continue
            trip_id = event.get('trip_id')
            entries = event.get('presence')
            if not isinstance(trip_id, int) or not isinstance(entries, list):
                continue
            clean = _dedupe([item for item in entries if isinstance(item, dict)])
            _shared_presence[trip_id] = clean
            room = _rooms.get(trip_id)
            if room is not None:
                await broadcast(room, {'type': 'presence', 'presence': clean})
    finally:
        try:
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass

async def _listen_forever() -> None:
    while redis_bus.available():
        if redis_bus.client() is None:
            # Redis 故障退避期间不空转：等客户端恢复后重新订阅。
            await asyncio.sleep(1)
            continue
        try:
            await _listen_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 订阅断线后自动重连，presence 不能永久失联
            log.warning('Redis 实时频道断开，1 秒后重连：%s', type(exc).__name__)
            await asyncio.sleep(1)

async def _ensure_listener() -> None:
    global _listener_task
    if redis_bus.client() is None:
        return
    async with _listener_lock:
        if _listener_task is None or _listener_task.done():
            _listener_task = asyncio.create_task(_listen_forever(), name='trip-live-redis')

async def broadcast_presence(room: Room) -> None:
    """广播当前在线名单：连接与断开都调用，前端据此显示在线人数。"""
    client = redis_bus.client()
    if client is not None:
        try:
            entries = await _redis_presence(room.trip_id)
            _shared_presence[room.trip_id] = entries
            await _ensure_listener()
        except Exception as exc:  # noqa: BLE001 - Redis 故障时退化为本地名单
            log.warning('读取 Redis 在线名单失败（trip_id=%s）：%s', room.trip_id, type(exc).__name__)
            redis_bus.mark_failure()
            _shared_presence.pop(room.trip_id, None)
            entries = presence(room)
    else:
        entries = presence(room)
    await broadcast(room, {'type': 'presence', 'presence': entries})
    if client is not None:
        try:
            await _publish({'type': 'presence', 'trip_id': room.trip_id, 'presence': entries})
        except Exception as exc:  # noqa: BLE001 - 发布失败只影响其它 worker，本进程已广播
            log.warning('发布 Redis 在线名单失败（trip_id=%s）：%s', room.trip_id, type(exc).__name__)

async def touch(connection: Connection, trip_id: int) -> None:
    """心跳续约：延长该连接在 Redis 中的存活时间。"""
    try:
        await _redis_touch(connection, trip_id)
    except Exception as exc:  # noqa: BLE001 - 心跳续约失败不能影响 pong
        log.warning('续约 Redis 在线状态失败（trip_id=%s）：%s', trip_id, type(exc).__name__)
        redis_bus.mark_failure()

async def join(trip_id: int, connection: Connection, version: int) -> Room:
    """加入房间并确保版本 watcher 在跑；返回房间，调用方据此发 hello。"""
    room = _rooms.get(trip_id)
    if room is None:
        room = Room(trip_id, version)
        _rooms[trip_id] = room
    room.connections.append(connection)
    if redis_bus.client() is not None:
        try:
            await _redis_touch(connection, trip_id)
            _shared_presence[trip_id] = await _redis_presence(trip_id)
            await _ensure_listener()
        except Exception as exc:  # noqa: BLE001 - Redis 故障时按本地房间继续工作
            log.warning('登记 Redis 在线状态失败（trip_id=%s）：%s', trip_id, type(exc).__name__)
            redis_bus.mark_failure()
            _shared_presence.pop(trip_id, None)
    if room.watcher is None or room.watcher.done():
        room.watcher = asyncio.create_task(watch(room), name=f'trip-live-{trip_id}')
    return room

async def remove(room: Room, connection: Connection) -> bool:
    """把连接移出房间并广播新名单；房间空了就顺手取消 watcher 并丢弃。

    返回房间是否已空。广播在本函数内完成，调用方无需再调用 broadcast_presence，
    避免断开路径重复推送。
    """
    if connection in room.connections:
        room.connections.remove(connection)
    empty = not room.connections
    client = redis_bus.client()
    if client is not None:
        try:
            await _redis_leave(connection, room.trip_id)
            entries = await _redis_presence(room.trip_id)
            _shared_presence[room.trip_id] = entries
            await broadcast(room, {'type': 'presence', 'presence': entries})
            await _publish({'type': 'presence', 'trip_id': room.trip_id, 'presence': entries})
        except Exception as exc:  # noqa: BLE001 - 清理失败也必须继续，不能留下幽灵连接
            log.warning('清理 Redis 在线状态失败（trip_id=%s）：%s', room.trip_id, type(exc).__name__)
            redis_bus.mark_failure()
            _shared_presence.pop(room.trip_id, None)
            if not empty:
                await broadcast(room, {'type': 'presence', 'presence': presence(room)})
    elif not empty:
        await broadcast(room, {'type': 'presence', 'presence': presence(room)})
    if empty:
        discard(room)
    return empty

def discard(room: Room) -> None:
    """丢弃房间并停掉 watcher；重复调用安全。"""
    if _rooms.get(room.trip_id) is room:
        _rooms.pop(room.trip_id, None)
    task, room.watcher = room.watcher, None
    if task is not None and not task.done():
        task.cancel()

def snapshot(trip_id: int) -> tuple[int, dict | None] | None:
    """读一次版本快照，返回 (version, 最近编辑者)；行程不存在/已删除返回 None。"""
    with app_db.Session() as db:
        trip = db.get(Trip, trip_id)
        if trip is None or trip.deleted_at:
            return None
        editor = None
        if trip.last_edited_by:
            user = db.scalar(select(User).where(User.username == trip.last_edited_by))
            if user is not None:
                editor = {'user_id': user.id, 'username': user.username}
        return trip.version or 0, editor

async def watch(room: Room) -> None:
    """版本 watcher：每 LIVE_POLL_SECONDS 读一次 version，变了才广播，避免空转刷消息。"""
    while True:
        await asyncio.sleep(LIVE_POLL_SECONDS)
        try:
            # snapshot 是同步 SQLAlchemy 查询，放到线程池，避免每个房间每 1.5 秒阻塞事件循环。
            current = await asyncio.to_thread(snapshot, room.trip_id)
        except Exception as exc:  # noqa: BLE001 —— 一次读库失败不能让 watcher 退出，否则此后再无推送
            log.warning('实时协同版本轮询失败（trip_id=%s）：%s', room.trip_id, type(exc).__name__)
            continue
        if current is None:
            # 行程被删除：房间连接随后会因 HTTP 授权失效而断开，这里不主动踢人。
            continue
        version, editor = current
        if version == room.version:
            continue
        room.version = version
        await broadcast(room, {'type': 'trip_updated', 'version': version, 'by': editor})

async def shutdown() -> None:
    """应用退出：停掉 Redis 订阅与所有 watcher，避免测试/热重载留下后台任务。"""
    global _listener_task
    task, _listener_task = _listener_task, None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    for room in list(_rooms.values()):
        discard(room)
    _rooms.clear()
    _shared_presence.clear()
