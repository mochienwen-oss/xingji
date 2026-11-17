"""需求驱动的完整流程测试：分享链接 → 协作 → 版本冲突 → 软删除/恢复 → 高德降级。

每条断言的预期都来自需求文本（README.md），不照抄实现细节：
- 第 91 行：行程所有者可生成只读分享链接，并可撤销该行程的所有链接；也可生成 8 位
  分享码，朋友输入后成为可编辑协作者，页面显示当前在线人数并同步其他人的保存；分享码
  可随时停用或轮换；分享页展示已保存的地点、活动、时间和路线，不包含对话、预算或待规划
  池；删除行程期间分享链接不可访问。
- 第 102 行：高德地点详情有 5 分钟进程内缓存，协作者轮询和分享页刷新不会每次重新请求
  全部地点。
"""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import backend.db as app_db
from backend.db import Trip
from backend.main import app
from backend.api import shares
from backend.services import join_codes, ratelimit, trip_places
from tests.conftest import login


def visitor_client():
    """未登录访客：分享链接对未登录设备也能打开（README 第 91 行）。"""
    return TestClient(app)


def make_trip(c, days=2, city='杭州'):
    body = {
        'city': city,
        'days': days,
        'budget': 'private-budget',
        'conversation': [{'role': 'user', 'content': 'private-chat'}],
    }
    response = c.post('/api/trips', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_share_link_is_read_only_and_excludes_private_data(client):
    c, _ = client
    login(c)
    trip = make_trip(c)

    # 分享是所有者权限：协作者/陌生人不能替别人生成链接。
    login(c, 'bob', 'password2')
    assert c.post(f"/api/trips/{trip['id']}/share").status_code == 404

    login(c)
    response = c.post(f"/api/trips/{trip['id']}/share")
    assert response.status_code == 200, response.text
    token = response.json()['token']

    visitor = visitor_client()
    view = visitor.post('/api/shares/view', json={'token': token})
    assert view.status_code == 200, view.text
    body = view.json()
    assert body['id'] == trip['id']
    assert body['request']['city'] == '杭州'
    assert body['request']['days'] == 2
    assert set(body['request']) <= {'city', 'days', 'start_date', 'transport'}
    assert len(body['days']) == 2
    assert body['days'][0]['stops'], '分享页必须展示已保存的地点'

    # 分享页只给公开摘要：地点字段白名单，且原文里不能出现对话与预算。
    place_fields = set(body['days'][0]['stops'][0]['place'])
    assert place_fields <= {'id', 'name', 'address', 'location', 'opentime', 'cost',
                            'source_time', 'photos', 'unavailable'}
    dumped = json.dumps(body, ensure_ascii=False)
    assert 'private-chat' not in dumped
    assert 'private-budget' not in dumped
    for key in ('conversation', 'budget', 'backlog'):
        assert key not in body

    # 未登录也能打开落地页；但只读，不能借分享写行程。
    assert visitor.get(f'/s/{token}').status_code == 200
    assert visitor.put(f"/api/trips/{trip['id']}/days",
                       json={'days': []}).status_code == 401


def test_regenerate_and_revoke_invalidate_old_links_everywhere(client):
    c, _ = client
    login(c)
    trip = make_trip(c, days=1)
    first = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    second = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    assert first != second, '重新生成分享链接应当只保留最新一条有效'
    visitor = visitor_client()
    assert visitor.post('/api/shares/view', json={'token': first}).status_code == 404
    assert visitor.get(f'/s/{first}').status_code == 404
    assert visitor.post('/api/shares/view', json={'token': second}).status_code == 200

    # 朋友凭仍有效的链接拿走一份副本：副本不带原作者的 AI 对话。
    login(c, 'bob', 'password2')
    fork = c.post('/api/shares/fork', json={'token': second})
    assert fork.status_code == 201, fork.text
    copy = fork.json()
    assert copy['id'] != trip['id']
    assert copy['conversation'] == []

    # 撤销该行程的全部链接后，查看/复制/落地页三个入口同时失效。
    login(c)
    assert c.delete(f"/api/trips/{trip['id']}/share").status_code == 200
    status = c.get(f"/api/trips/{trip['id']}/share-status").json()
    assert status['link_active'] is False
    assert status['visibility'] == 'private'
    visitor = visitor_client()
    login(c, 'bob', 'password2')
    for token in (first, second):
        assert visitor.post('/api/shares/view', json={'token': token}).status_code == 404
        assert visitor.get(f'/s/{token}').status_code == 404
        assert c.post('/api/shares/fork', json={'token': token}).status_code == 404


def test_join_code_makes_editable_collaborator_and_can_rotate_and_disable(client):
    c, places = client
    login(c)
    trip = make_trip(c)
    code = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']
    assert len(code) == 8, '分享码是 8 位'
    assert set(code) <= set(join_codes.ALPHABET)

    # 朋友输入分享码（大小写与首尾空格容错）后成为可编辑协作者。
    login(c, 'bob', 'password2')
    joined = c.post('/api/trips/join', json={'code': f'  {code.lower()}  '})
    assert joined.status_code == 200, joined.text
    assert joined.json()['trip_id'] == trip['id']
    assert joined.json()['already_member'] is False

    detail = c.get(f"/api/trips/{trip['id']}").json()
    assert detail['is_owner'] is False
    days = deepcopy(detail['days'])
    days[0]['stops'].append({'place': places[2], 'duration': 60, 'reason': ''})
    saved = c.put(f"/api/trips/{trip['id']}/days",
                  json={'days': days, 'version': detail['version']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['version'] == detail['version'] + 1
    assert saved.json()['last_edited_by'] == 'bob'

    # 协作列表：owner、成员数与角色对协作者可见（README 第 91 行的“协作”视图）。
    shared = c.get('/api/trips/shared').json()['trips']
    assert len(shared) == 1
    assert shared[0]['id'] == trip['id']
    assert shared[0]['is_owner'] is False
    assert shared[0]['owner'] == 'alice'
    assert shared[0]['member_count'] == 2
    assert shared[0]['role'] == 'edit'

    # 协作者不能行使所有者权限：轮换/停用分享码、生成链接、删除行程。
    assert c.post(f"/api/trips/{trip['id']}/join-code", json={'rotate': True}).status_code == 404
    assert c.delete(f"/api/trips/{trip['id']}/join-code").status_code == 404
    assert c.post(f"/api/trips/{trip['id']}/share").status_code == 404
    assert c.delete(f"/api/trips/{trip['id']}").status_code == 404

    # 重复输入同一个码是幂等的，不会重复加人。
    ratelimit.reset()  # 测试钩子：/api/trips/join 容量 5 次/30s
    again = c.post('/api/trips/join', json={'code': code})
    assert again.status_code == 200
    assert again.json()['already_member'] is True

    # 轮换后旧码立即失效，新码可用；再停用则谁也用不了。
    login(c)
    rotated = c.post(f"/api/trips/{trip['id']}/join-code", json={'rotate': True}).json()['code']
    assert rotated != code
    assert c.get(f"/api/trips/{trip['id']}/join-code").json()['code'] == rotated
    ratelimit.reset()
    registered = c.post('/api/register', json={'username': 'carol', 'password': 'password3',
                                               'accept_terms': True})
    assert registered.status_code == 200, registered.text
    assert c.post('/api/trips/join', json={'code': code}).status_code == 404
    assert c.post('/api/trips/join', json={'code': rotated}).json()['already_member'] is False

    # 已加入的协作者退出后与陌生人一致（404）。
    assert c.delete(f"/api/trips/{trip['id']}/members/me").status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404

    login(c)
    assert c.delete(f"/api/trips/{trip['id']}/join-code").status_code == 204
    assert c.get(f"/api/trips/{trip['id']}/join-code").json()['code'] is None
    login(c, 'carol', 'password3')
    ratelimit.reset()
    disabled = c.post('/api/trips/join', json={'code': rotated})
    assert disabled.status_code == 404
    assert disabled.json()['detail'] == join_codes.INVALID_MESSAGE
    # 已加入的协作者不受停用影响。
    login(c, 'bob', 'password2')
    assert c.get(f"/api/trips/{trip['id']}").status_code == 200


def test_removing_collaborator_revokes_share_code(client):
    """移除协作者即吊销分享码：否则被移除的人拿旧码立刻能加回来，移除等于没做。

    README 第 91 行：分享码可随时停用或轮换；移除协作者后与陌生人一致。
    """
    c, _ = client
    login(c)
    trip = make_trip(c, days=1)
    code = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']

    login(c, 'bob', 'password2')
    ratelimit.reset()
    assert c.post('/api/trips/join', json={'code': code}).status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").status_code == 200

    login(c)
    members = c.get(f"/api/trips/{trip['id']}/collaborators").json()['members']
    bob_id = next(m['user_id'] for m in members if m['username'] == 'bob')
    assert c.delete(f"/api/trips/{trip['id']}/collaborators/{bob_id}").status_code == 200
    assert [m['username'] for m in c.get(f"/api/trips/{trip['id']}/collaborators").json()['members']] == ['alice']

    # 被移除的人与陌生人一致。
    login(c, 'bob', 'password2')
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404
    registered = c.post('/api/register', json={'username': 'carol', 'password': 'password3',
                                               'accept_terms': True})
    assert registered.status_code == 200, registered.text
    ratelimit.reset()
    revoked = c.post('/api/trips/join', json={'code': code})
    assert revoked.status_code == 404
    assert revoked.json()['detail'] == join_codes.INVALID_MESSAGE

    # 所有者可重新生成新码，新码仍然可用（吊销的是这一枚码，不是邀请能力）。
    login(c)
    fresh = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']
    assert fresh and fresh != code
    login(c, 'carol', 'password3')
    ratelimit.reset()
    rejoined = c.post('/api/trips/join', json={'code': fresh})
    assert rejoined.status_code == 200 and rejoined.json()['already_member'] is False


def test_deleted_trip_hides_shares_and_restore_keeps_them_revoked(client):
    c, _ = client
    login(c)
    trip = make_trip(c, days=1)
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    code = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']

    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200
    visitor = visitor_client()
    assert visitor.post('/api/shares/view', json={'token': token}).status_code == 404
    assert visitor.get(f'/s/{token}').status_code == 404
    login(c, 'bob', 'password2')
    assert c.post('/api/shares/fork', json={'token': token}).status_code == 404
    ratelimit.reset()
    assert c.post('/api/trips/join', json={'code': code}).status_code == 404

    # 回收站里仍可见并给出删除时间，7 天内可恢复。
    login(c)
    trash = c.get('/api/trips', params={'deleted': 'true'}).json()
    assert [item['id'] for item in trash] == [trip['id']]
    assert trash[0]['deleted_at']
    assert c.post(f"/api/trips/{trip['id']}/restore").status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").status_code == 200
    assert [item['id'] for item in c.get('/api/trips').json()] == [trip['id']]

    # 删除即撤销对外授权：恢复行程不会把旧分享链接一起复活。
    extra = visitor_client()
    assert extra.post('/api/shares/view', json={'token': token}).status_code == 404
    assert extra.get(f'/s/{token}').status_code == 404


def test_save_version_conflict_protects_concurrent_collaboration(client):
    c, _ = client
    login(c)
    trip = make_trip(c)
    stale_version = trip['version']
    code = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']
    login(c, 'bob', 'password2')
    assert c.post('/api/trips/join', json={'code': code}).status_code == 200

    bob_view = c.get(f"/api/trips/{trip['id']}").json()
    bob_days = deepcopy(bob_view['days'])
    bob_days[1]['stops'][0]['activity'] = '拍照'
    saved = c.put(f"/api/trips/{trip['id']}/days",
                  json={'days': bob_days, 'version': bob_view['version']})
    assert saved.status_code == 200, saved.text

    # 所有者拿着旧版本保存：必须 409 提示重新打开，且不能覆盖协作者刚保存的内容。
    login(c)
    conflict = c.put(f"/api/trips/{trip['id']}/days",
                     json={'days': deepcopy(trip['days']), 'version': stale_version})
    assert conflict.status_code == 409
    assert '重新打开行程' in conflict.json()['detail']

    fresh = c.get(f"/api/trips/{trip['id']}").json()
    assert fresh['version'] == stale_version + 1
    assert fresh['last_edited_by'] == 'bob'
    assert fresh['days'][1]['stops'][0]['activity'] == '拍照'

    # 带最新版本重试即可保存。
    retry = c.put(f"/api/trips/{trip['id']}/days",
                  json={'days': deepcopy(fresh['days']), 'version': fresh['version']})
    assert retry.status_code == 200, retry.text
    assert retry.json()['version'] == fresh['version'] + 1


def test_share_view_shows_saved_times_activities_and_routes(client):
    c, places = client
    login(c)
    trip = make_trip(c)
    detail = c.get(f"/api/trips/{trip['id']}").json()
    days = deepcopy(detail['days'])
    days[0]['stops'][0]['activity'] = '看日落'
    days[0]['stops'][0]['fixed_time'] = '17:30'
    days[0]['start_time'] = '09:00'
    days[0]['end_time'] = '21:00'
    days[0]['stops'].append({'place': places[2], 'duration': 60, 'reason': '顺路'})
    saved = c.put(f"/api/trips/{trip['id']}/days",
                  json={'days': days,
                        'backlog': [{'place': places[3], 'duration': 90, 'reason': ''}],
                        'version': detail['version']})
    assert saved.status_code == 200, saved.text
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']

    body = visitor_client().post('/api/shares/view', json={'token': token}).json()
    day = body['days'][0]
    assert day['start_time'] == '09:00'
    assert day['end_time'] == '21:00'
    assert day['stops'][0]['activity'] == '看日落'
    assert day['stops'][0]['fixed_time'] == '17:30'
    assert len(day['stops']) == 2
    assert day['routes'], '分享页要展示已保存的相邻路线'
    assert day['routes'][0]['duration'] == 600
    assert day['routes'][0]['mode'] in ('walking', 'driving', 'transit')
    # 待规划池里的地点不在分享页的日程里。
    planned = {stop['place']['id'] for item in body['days'] for stop in item['stops']}
    assert places[3]['id'] not in planned


def test_share_snapshot_reuses_cache_and_survives_amap_outage(client, monkeypatch):
    c, _ = client
    shares.reset_cache()
    login(c)
    trip = make_trip(c, days=1)
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    visitor = visitor_client()
    assert visitor.post('/api/shares/view', json={'token': token}).status_code == 200

    # README 第 102 行：5 分钟内同一份数据重复刷新分享页不会重新请求高德。
    calls = []
    original = trip_places.refresh

    async def counting_refresh(data):
        calls.append(1)
        return await original(data)

    monkeypatch.setattr(trip_places, 'refresh', counting_refresh)
    assert visitor.post('/api/shares/view', json={'token': token}).status_code == 200
    assert calls == []

    # 行程内容变了（改出发日期），缓存按数据哈希自然失效。
    detail = c.get(f"/api/trips/{trip['id']}").json()
    assert c.put(f"/api/trips/{trip['id']}/start-date",
                 json={'start_date': '2026-12-01',
                       'version': detail['version']}).status_code == 200

    # 此时高德不可用：分享页要回落到上次成功快照并给出提示，而不是 500 或空白。
    async def broken_refresh(data):
        raise RuntimeError('amap down')

    monkeypatch.setattr(trip_places, 'refresh', broken_refresh)
    fallback = visitor.post('/api/shares/view', json={'token': token})
    assert fallback.status_code == 200, fallback.text
    body = fallback.json()
    assert body['days'] and body['days'][0]['stops']
    assert body['place_notice']
    assert visitor.get(f'/s/{token}').status_code == 200

    # 高德恢复后重新读取真实数据，提示消失。
    monkeypatch.setattr(trip_places, 'refresh', original)
    recovered = visitor.post('/api/shares/view', json={'token': token})
    assert recovered.status_code == 200
    assert not recovered.json()['place_notice']


def test_restore_does_not_revive_share_code(client):
    """删除行程即收回对外授权：恢复后旧分享码不能继续把朋友放进来。

    需求出处：README 第 91 行（分享码可随时停用/轮换）与删除语义——同一次删除里分享链接
    被撤销且恢复后也不复活，分享码属于同一类对外授权，删除时就该作废；恢复只恢复行程，
    要不要重新开放协作由创建者重新生成。
    """
    c, _ = client
    login(c)
    trip = make_trip(c, days=1)
    code = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']
    assert code and len(code) == 8

    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200
    assert c.post(f"/api/trips/{trip['id']}/restore").status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").status_code == 200

    # 旧码不能在恢复后的行程上复活。
    ratelimit.reset()  # /api/trips/join 容量 5 次/30s
    login(c, 'bob', 'password2')
    revived = c.post('/api/trips/join', json={'code': code})
    assert revived.status_code == 404
    assert revived.json()['detail'] == join_codes.INVALID_MESSAGE

    # 恢复后由创建者重新决定是否开放协作：新码可用。
    login(c)
    assert c.get(f"/api/trips/{trip['id']}/join-code").json()['code'] is None
    new_code = c.post(f"/api/trips/{trip['id']}/join-code", json={}).json()['code']
    assert new_code and new_code != code
    ratelimit.reset()
    login(c, 'bob', 'password2')
    joined = c.post('/api/trips/join', json={'code': new_code})
    assert joined.status_code == 200, joined.text
    assert joined.json()['already_member'] is False

def test_restore_window_is_seven_days(client):
    """回收站保留 7 天：刚好在窗口内可恢复，超过窗口给明确 404，且条目留在回收站等后台清理。

    需求出处：README 软删除/回收站约定（7 天内可找回）+ CHANGELOG 0.3.0「过期清理移出
    请求路径、改每小时后台任务」——所以超期条目不能在读取列表时被顺手删掉，只能由
    maintenance 清理；这里只验证恢复接口的时间边界与提示文案。
    """
    c, _ = client
    login(c)
    inside = make_trip(c, days=1)
    outside = make_trip(c, days=1)

    assert c.delete(f"/api/trips/{inside['id']}").status_code == 200
    assert c.delete(f"/api/trips/{outside['id']}").status_code == 200
    with app_db.Session() as db:
        db.get(Trip, inside['id']).deleted_at = (
            datetime.now(timezone.utc) - timedelta(days=6, hours=23, minutes=55)).isoformat()
        db.get(Trip, outside['id']).deleted_at = (
            datetime.now(timezone.utc) - timedelta(days=7, minutes=1)).isoformat()
        db.commit()

    assert c.post(f"/api/trips/{inside['id']}/restore").status_code == 200
    assert c.get(f"/api/trips/{inside['id']}").status_code == 200

    late = c.post(f"/api/trips/{outside['id']}/restore")
    assert late.status_code == 404
    assert late.json()['detail'] == '该行程已超过 7 天，无法找回。'
    # 前台读取不负责清理：超期条目仍在回收站，等维护任务统一清除。
    trash = [item['id'] for item in c.get('/api/trips', params={'deleted': 'true'}).json()]
    assert trash == [outside['id']]
