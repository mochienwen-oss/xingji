"""WebSocket 实时协同：在线 presence、鉴权与版本 watcher。"""
import json
import threading
import time

from sqlalchemy import select

import backend.db as app_db
import backend.main as main  # 确保 app 与路由已装配
from backend.db import Trip, User
from backend.services import live
from tests.conftest import login

assert main.app is not None


def _create_trip(c):
    resp = c.post('/api/trips', json={'city': '杭州', 'days': 2, 'travelers': 2, 'transport': 'transit'})
    assert resp.status_code == 201, resp.text
    return resp.json()['id']


def _user_id(username):
    with app_db.Session() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _login_cookie(c, username, password):
    """登录目标用户取 cookie，再把当前会话切回 alice。

    同一个 TestClient 的 cookie jar 只保留最近一次登录，第二个连接因此显式带 Cookie 头；
    starlette 的 cookies 优先用显式头，不会被 jar 覆盖。
    """
    login(c, username, password)
    token = c.cookies.get('trip_session')
    assert token
    login(c)
    return f'trip_session={token}'


def _receive(ws, timeout=5.0):
    """给 receive 加超时：TestClient 的 receive 没有超时，消息不来会永久阻塞。"""
    box = {}
    done = threading.Event()

    def worker():
        try:
            box['value'] = ws.receive()
        except BaseException as exc:  # noqa: BLE001 —— 线程内异常带回主线程断言
            box['error'] = exc
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    if not done.wait(timeout):
        raise AssertionError('等待 WebSocket 消息超时')
    if 'error' in box:
        raise box['error']
    return box['value']


def _receive_json(ws, expected=None, timeout=5.0, predicate=None):
    """按 type 或自定义条件过滤接收：watcher、presence 与自己的 hello 可能交叉。"""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f'等待 {expected or "任意"} 消息超时')
        message = _receive(ws, remaining)
        if message['type'] == 'websocket.close':
            raise AssertionError(f'连接被关闭，code={message.get("code")}')
        payload = json.loads(message['text'])
        if predicate is not None:
            if predicate(payload):
                return payload
            continue
        if expected is None or payload.get('type') == expected:
            return payload


def _presence_ids(payload):
    return sorted(item['user_id'] for item in payload.get('presence', []))


def _close_code(ws, timeout=5.0):
    """读关闭帧：先 accept 再 close，客户端才能拿到 4401/4403/4404 这类业务码。"""
    message = _receive(ws, timeout)
    assert message['type'] == 'websocket.close', message
    return message['code']


def test_hello_contains_presence_and_you(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as ws:
        hello = _receive_json(ws, 'hello')
    assert hello['trip_id'] == trip_id
    assert hello['version'] == 0
    assert hello['you'] == {'user_id': _user_id('alice'), 'username': 'alice'}
    assert hello['presence'] == [hello['you']]


def test_two_users_see_each_other_and_leave_updates_presence(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    bob_cookie = _login_cookie(c, 'bob', 'password2')
    # 先用分享码把 bob 加成协作者，否则他会被当成非成员挡在 4403。
    code = c.post(f'/api/trips/{trip_id}/join-code', json={'rotate': False}).json()['code']
    joined = c.post('/api/trips/join', json={'code': code}, headers={'cookie': bob_cookie})
    assert joined.status_code == 200
    assert joined.json()['already_member'] is False
    alice_id, bob_id = _user_id('alice'), _user_id('bob')
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as alice:
        hello = _receive_json(alice, 'hello')
        assert [item['user_id'] for item in hello['presence']] == [alice_id]
        with c.websocket_connect(f'/api/trips/{trip_id}/live', headers={'cookie': bob_cookie}) as bob:
            bob_hello = _receive_json(bob, 'hello')
            assert bob_hello['you']['user_id'] == bob_id
            assert {item['user_id'] for item in bob_hello['presence']} == {alice_id, bob_id}
            # alice 自己加入时不重复看自己那条，等到 bob 进来后的两人名单。
            presence = _receive_json(
                alice,
                predicate=lambda payload: payload.get('type') == 'presence'
                and _presence_ids(payload) == [alice_id, bob_id],
            )
            assert _presence_ids(presence) == [alice_id, bob_id]
        # bob 断开后，alice 收到只剩自己的在线名单。
        after = _receive_json(
            alice,
            predicate=lambda payload: payload.get('type') == 'presence'
            and _presence_ids(payload) == [alice_id],
        )
        assert _presence_ids(after) == [alice_id]


def test_same_user_two_tabs_counted_once(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    alice_id = _user_id('alice')
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as first:
        _receive_json(first, 'hello')
        with c.websocket_connect(f'/api/trips/{trip_id}/live') as second:
            hello = _receive_json(second, 'hello')
            assert [item['user_id'] for item in hello['presence']] == [alice_id]
        after = _receive_json(first, 'presence')
        assert [item['user_id'] for item in after['presence']] == [alice_id]


def test_ping_returns_pong_and_other_types_ignored(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as ws:
        _receive_json(ws, 'hello')
        ws.send_json({'type': 'ping'})
        assert _receive_json(ws, 'pong') == {'type': 'pong'}
        # 未知类型与坏帧静默忽略，不影响后续 ping。
        ws.send_json({'type': 'whatever', 'value': 1})
        ws.send_text('not json')
        ws.send_json({'type': 'ping'})
        assert _receive_json(ws, 'pong') == {'type': 'pong'}


def test_unauthenticated_connection_closed_4401(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    c.cookies.clear()
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as ws:
        assert _close_code(ws) == 4401


def test_non_member_closed_4403(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    bob_cookie = _login_cookie(c, 'bob', 'password2')
    with c.websocket_connect(f'/api/trips/{trip_id}/live', headers={'cookie': bob_cookie}) as ws:
        assert _close_code(ws) == 4403


def test_missing_or_deleted_trip_closed_4404(client):
    c, _ = client
    login(c)
    with c.websocket_connect('/api/trips/999999/live') as ws:
        assert _close_code(ws) == 4404
    trip_id = _create_trip(c)
    assert c.delete(f'/api/trips/{trip_id}').status_code == 200
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as ws:
        assert _close_code(ws) == 4404


def test_watcher_broadcasts_trip_updated(client, monkeypatch):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    alice_id = _user_id('alice')
    # 轮询间隔调小：不依赖真实 1.5 秒，测试在毫秒级拿到推送。
    monkeypatch.setattr(live, 'LIVE_POLL_SECONDS', 0.05)
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as ws:
        _receive_json(ws, 'hello')
        with app_db.Session() as db:
            row = db.get(Trip, trip_id)
            row.version = 3
            row.last_edited_by = 'alice'
            db.commit()
        update = _receive_json(ws, 'trip_updated')
    assert update['version'] == 3
    assert update['by'] == {'user_id': alice_id, 'username': 'alice'}


def test_online_count_dedupes_and_defaults_zero(client):
    """online_count 纯内存计数：同一用户多标签页只算 1 人，无房间/全部断开后为 0。"""
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    assert live.online_count(trip_id) == 0
    assert live.online_count(999999) == 0
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as first:
        _receive_json(first, 'hello')
        assert live.online_count(trip_id) == 1
        with c.websocket_connect(f'/api/trips/{trip_id}/live') as second:
            _receive_json(second, 'hello')
            # 同一个人开两个标签页，仍只算 1 位在线规划者。
            assert live.online_count(trip_id) == 1
        assert live.online_count(trip_id) == 1
    assert live.online_count(trip_id) == 0


def _receive_close(ws, timeout=5.0):
    """读到关闭帧为止：连接刚建立时的 presence 广播可能排在关闭帧前面。"""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError('等待 WebSocket 关闭帧超时')
        message = _receive(ws, remaining)
        if message['type'] == 'websocket.close':
            return message['code']
        # 其它消息（presence 广播等）跳过，继续等关闭帧。


def _join_bob(c, trip_id, bob_cookie):
    """把 bob 加成协作者：实时入口要求成员身份，否则会被 4403 挡在门外。"""
    code = c.post(f'/api/trips/{trip_id}/join-code', json={'rotate': False}).json()['code']
    joined = c.post('/api/trips/join', json={'code': code}, headers={'cookie': bob_cookie})
    assert joined.status_code == 200, joined.text


def test_heartbeat_after_logout_closes_4401_and_drops_presence(client):
    """退出登录会让 session_version +1：心跳复核发现旧 token 失效，立即断开并广播新名单。"""
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    bob_cookie = _login_cookie(c, 'bob', 'password2')
    _join_bob(c, trip_id, bob_cookie)
    alice_id, bob_id = _user_id('alice'), _user_id('bob')
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as alice:
        _receive_json(alice, 'hello')
        with c.websocket_connect(f'/api/trips/{trip_id}/live', headers={'cookie': bob_cookie}) as bob:
            _receive_json(bob, 'hello')
            _receive_json(
                alice,
                predicate=lambda payload: payload.get('type') == 'presence'
                and _presence_ids(payload) == [alice_id, bob_id],
            )
            # 模拟 bob 在别的设备/标签页退出登录：服务端会话版本前进，旧 token 立即失效。
            with app_db.Session() as db:
                bob_user = db.scalar(select(User).where(User.username == 'bob'))
                bob_user.session_version = (bob_user.session_version or 0) + 1
                db.commit()
            bob.send_json({'type': 'ping'})
            assert _receive_close(bob) == 4401
            after = _receive_json(
                alice,
                predicate=lambda payload: payload.get('type') == 'presence'
                and _presence_ids(payload) == [alice_id],
            )
            assert _presence_ids(after) == [alice_id]
    assert live.online_count(trip_id) == 0


def test_heartbeat_after_removal_closes_4403_and_drops_presence(client):
    """owner 移除协作者后，对方的心跳复核发现已不是成员，连接断开且不再算在线。"""
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    bob_cookie = _login_cookie(c, 'bob', 'password2')
    _join_bob(c, trip_id, bob_cookie)
    alice_id, bob_id = _user_id('alice'), _user_id('bob')
    with c.websocket_connect(f'/api/trips/{trip_id}/live') as alice:
        _receive_json(alice, 'hello')
        with c.websocket_connect(f'/api/trips/{trip_id}/live', headers={'cookie': bob_cookie}) as bob:
            _receive_json(bob, 'hello')
            _receive_json(
                alice,
                predicate=lambda payload: payload.get('type') == 'presence'
                and _presence_ids(payload) == [alice_id, bob_id],
            )
            assert c.delete(f'/api/trips/{trip_id}/collaborators/{bob_id}').status_code == 200
            bob.send_json({'type': 'ping'})
            assert _receive_close(bob) == 4403
            after = _receive_json(
                alice,
                predicate=lambda payload: payload.get('type') == 'presence'
                and _presence_ids(payload) == [alice_id],
            )
            assert _presence_ids(after) == [alice_id]
    assert live.online_count(trip_id) == 0
