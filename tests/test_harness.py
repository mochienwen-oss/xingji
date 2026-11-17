"""Harness 会话：事件协议、表单补丁、排程、压缩、改稿与记忆开关。"""
import json

from backend.services.harness import orchestrator
from backend.services.harness import context as harness_context
from backend.services import planning as planning_service
from tests.conftest import login


def collect(client, payload):
    """POST 会话流并返回解析后的事件列表。"""
    events = []
    with client.stream('POST', '/api/planning/session/stream', json=payload) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith('data:'):
                continue
            events.append(json.loads(line[5:].strip()))
    return events


def kinds(events):
    return [event['kind'] for event in events]


def fake_intake(monkeypatch, result):
    async def model_json(messages, max_tokens=4000, on_reply=None):
        return result
    monkeypatch.setattr(orchestrator, 'model_json', model_json)


def base_turn(**overrides):
    payload = {
        'mode': 'explore',
        'message': '我想去杭州玩两天，轻松一点',
        'messages': [],
        'places': [],
    }
    payload.update(overrides)
    return payload


def test_clarify_asks_one_question(client, monkeypatch):
    c, _ = client
    fake_intake(monkeypatch, {
        'reply': '先定个城市，我就能开始排。',
        'intent': 'clarify',
        'form_patch': {},
        'place_keywords': [],
        'question': '想去哪个城市？',
    })
    events = collect(c, base_turn(message='我想出去玩几天'))
    assert 'question' in kinds(events)
    question = next(event for event in events if event['kind'] == 'question')
    assert question['text'] == '想去哪个城市？'
    done = events[-1]
    assert done['kind'] == 'done'
    assert done['reply'] == '先定个城市，我就能开始排。'
    assert done['turn_count'] == 1


def test_form_patch_and_chat_reply(client, monkeypatch):
    c, _ = client
    fake_intake(monkeypatch, {
        'reply': '杭州两天刚好，可以慢慢逛。',
        'intent': 'chat',
        'form_patch': {'city': '杭州', 'days': 2, 'pace': '轻松', 'travelers': 99},
        'place_keywords': [],
        'question': '',
    })
    events = collect(c, base_turn())
    patch = next(event for event in events if event['kind'] == 'form_patch')
    # travelers 99 越界，必须被 Harness 丢掉；合法字段照常下发。
    assert patch['patch'] == {'city': '杭州', 'days': 2, 'pace': '轻松'}
    done = events[-1]
    assert done['kind'] == 'done'
    assert done['reply'] == '杭州两天刚好，可以慢慢逛。'
    assert 'plan' not in done


def test_intake_accepts_saved_places(client, monkeypatch):
    """收藏地点是 Place 模型，不再是 dict；非空 places 不能让 intake 崩溃。"""
    c, places = client
    captured = {}
    original_build = orchestrator.registry.build

    def build(scenario_name, **kwargs):
        captured['dynamic'] = kwargs.get('dynamic')
        return original_build(scenario_name, **kwargs)

    monkeypatch.setattr(orchestrator.registry, 'build', build)
    fake_intake(monkeypatch, {
        'reply': '收到，我会参考你收藏的地点。',
        'intent': 'clarify',
        'form_patch': {},
        'place_keywords': [],
        'question': '还想安排哪天？',
    })
    events = collect(c, base_turn(places=places[:2]))
    assert captured['dynamic']['已收藏地点'] == ['景点1', '景点2']
    assert events[-1]['kind'] == 'done'


def test_plan_intent_builds_preview(client, monkeypatch):
    c, places = client
    fake_intake(monkeypatch, {
        'reply': '好，我按两天轻松节奏排一版。',
        'intent': 'plan',
        'form_patch': {'city': '杭州', 'days': 2},
        'place_keywords': [],
        'question': '',
    })
    events = collect(c, base_turn())
    assert 'phase' in kinds(events)
    plan_events = [event for event in events if event['kind'] == 'plan']
    assert plan_events, kinds(events)
    plan = plan_events[0]['plan']
    assert plan['request']['city'] == '杭州'
    assert len(plan['days']) == 2
    assert plan['days'][0]['stops'][0]['place']['id'] in {place['id'] for place in places}
    done = events[-1]
    assert done['kind'] == 'done'
    assert done['plan']['days'] == plan['days']
    assert done['reply'].startswith('好，我按两天轻松节奏排一版。')
    assert '路线排好了' in done['reply']


def test_compaction_emits_summary_patch(client, monkeypatch):
    c, _ = client
    fake_intake(monkeypatch, {
        'reply': '收到。',
        'intent': 'chat',
        'form_patch': {},
        'place_keywords': [],
        'question': '',
    })
    summary = {
        'core_request': '杭州两天',
        'key_concepts': '轻松',
        'data_and_interfaces': '',
        'errors_and_fixes': '',
        'resolution_process': '',
        'all_user_messages': ['我想去杭州玩两天，轻松一点'],
        'pending_tasks': [],
        'current_work': '刚拿到需求',
        'next_action': '确认城市',
    }

    async def fake_compact(messages, previous=None, dynamic=None):
        return summary

    monkeypatch.setattr(orchestrator, 'compact', fake_compact)
    events = collect(c, base_turn(turn_count=8))
    assert 'summary_patch' in kinds(events)
    patch = next(event for event in events if event['kind'] == 'summary_patch')
    assert patch['summary']['core_request'] == '杭州两天'
    assert patch['turn_count'] == 9
    assert events[-1]['summary'] == summary


def test_revise_uses_preview_and_returns_new_days(client, monkeypatch):
    c, places = client
    login(c)
    request = {
        'city': '杭州', 'days': 1, 'start_date': None, 'travelers': 2,
        'interests': '', 'pace': '适中', 'budget': '', 'must_visit': '', 'transport': 'transit',
    }
    preview = {
        'request': request,
        'days': [{'stops': [{'place': places[0], 'duration': 90, 'reason': ''}], 'routes': []}],
        'backlog': [],
    }
    fake_intake(monkeypatch, {
        'reply': '我把第一天改轻松一点。',
        'intent': 'revise',
        'form_patch': {},
        'place_keywords': [],
        'question': '',
    })

    async def fake_keywords(message, current_days, current_backlog=None):
        return []

    monkeypatch.setattr(planning_service, 'adjustment_keywords', fake_keywords)

    async def fake_edits(request_arg, candidates, instruction, days, backlog, on_reply=None, **kwargs):
        if on_reply:
            on_reply('已调整')
        next_days = [{'stops': [{'place': places[1], 'duration': 60, 'reason': '更轻松'}], 'routes': []}]
        return {'days': next_days, 'backlog': [], 'reply': '把第一个点换成了更轻松的。', 'changed': True}

    monkeypatch.setattr(planning_service, 'suggest_edits', fake_edits)
    events = collect(c, base_turn(
        mode='preview', message='第一天轻松一点', preview=preview,
        form=request,
    ))
    plan_events = [event for event in events if event['kind'] == 'plan']
    assert plan_events, kinds(events)
    assert plan_events[0]['plan']['days'][0]['stops'][0]['place']['id'] == places[1]['id']
    done = events[-1]
    assert done['kind'] == 'done'
    assert done['plan']['days'][0]['stops'][0]['duration'] == 60
    assert done['reply'] == '把第一个点换成了更轻松的。'


def test_revise_searches_new_place_and_merges_candidates(client, monkeypatch):
    """用户点名的新地点不在候选时：先高德检索并入候选，再交给 suggest_edits。"""
    c, places = client
    login(c)
    request = {
        'city': '杭州', 'days': 1, 'start_date': None, 'travelers': 2,
        'interests': '', 'pace': '适中', 'budget': '', 'must_visit': '', 'transport': 'transit',
    }
    preview = {
        'request': request,
        'days': [{'stops': [{'place': places[0], 'duration': 90, 'reason': ''}], 'routes': []}],
        'backlog': [],
    }
    fake_intake(monkeypatch, {
        'reply': '我把柳浪闻莺加进下午。',
        'intent': 'revise',
        'form_patch': {},
        'place_keywords': [],
        'question': '',
    })
    found = {**places[0], 'id': 'POI-NEW-1', 'name': '柳浪闻莺'}

    async def fake_keywords(message, current_days, current_backlog=None):
        return ['柳浪闻莺']

    async def fake_search(city, keyword):
        assert city == '杭州'
        assert keyword == '柳浪闻莺'
        return [found, places[0]]  # 第二个已在候选里，必须去重

    captured = {}

    async def fake_edits(request_arg, candidates, instruction, days, backlog, on_reply=None, **kwargs):
        captured['candidates'] = candidates
        next_days = [{'stops': [{'place': found, 'duration': 90, 'reason': '西湖边的公园'}], 'routes': []}]
        return {'days': next_days, 'backlog': [], 'reply': '已把柳浪闻莺加到下午。', 'changed': True}

    monkeypatch.setattr(planning_service, 'adjustment_keywords', fake_keywords)
    monkeypatch.setattr(orchestrator.amap, 'search_places', fake_search)
    monkeypatch.setattr(planning_service, 'suggest_edits', fake_edits)
    events = collect(c, base_turn(
        mode='preview', message='帮我加一个西湖边的公园，比如柳浪闻莺', preview=preview,
        form=request,
    ))
    ids = [str(p['id']) for p in captured['candidates']]
    assert ids.count('POI-NEW-1') == 1
    assert str(places[0]['id']) in ids
    place_events = [event for event in events if event['kind'] == 'places']
    assert place_events, kinds(events)
    assert place_events[0]['keyword'] == '柳浪闻莺'
    assert [p['id'] for p in place_events[0]['places']] == ['POI-NEW-1']
    statuses = [event['text'] for event in events if event['kind'] == 'status']
    assert any('柳浪闻莺' in text for text in statuses)
    done = events[-1]
    assert done['kind'] == 'done'
    assert done['plan']['days'][0]['stops'][0]['place']['id'] == 'POI-NEW-1'
    assert done['reply'] == '已把柳浪闻莺加到下午。'


def test_memory_preference_requires_login_and_persists(client):
    c, _ = client
    assert c.get('/api/account/memory').status_code == 401
    login(c)
    assert c.get('/api/account/memory').json() == {'enabled': True}
    assert c.patch('/api/account/memory', json={'enabled': False}).json() == {'enabled': False}
    assert c.get('/api/account/memory').json() == {'enabled': False}


def test_needs_compaction_by_turns_and_messages():
    short = [{'role': 'user', 'content': '你好'}]
    assert not harness_context.needs_compaction(short)
    assert harness_context.needs_compaction(short, summary={'core_request': 'x'}, turn_count=8)
    many = [{'role': 'user', 'content': 'x'}] * 13
    assert harness_context.needs_compaction(many)
    # 已经有摘要后，消息条数会一直高于阈值；此时不能再靠条数每轮重复压缩。
    assert not harness_context.needs_compaction(many, summary={'core_request': 'x'})


def test_compacted_turn_only_passes_recent_history(client, monkeypatch):
    c, _ = client
    summary = {'core_request': '杭州两天', 'all_user_messages': ['旧消息']}
    captured = {}

    async def fake_compact(messages, previous=None, dynamic=None):
        return summary

    async def fake_intake(req, form, history, summary_arg, memories, emit):
        captured['history'] = history
        return {'reply': '收到。', 'intent': 'chat', 'form_patch': {}, 'place_keywords': [], 'question': ''}

    monkeypatch.setattr(orchestrator, 'compact', fake_compact)
    monkeypatch.setattr(orchestrator, '_intake', fake_intake)
    messages = [
        {'role': 'user' if index % 2 == 0 else 'assistant', 'content': f'第 {index} 条'}
        for index in range(13)
    ]
    collect(c, base_turn(turn_count=8, messages=messages))
    assert len(captured['history']) == 4
    assert captured['history'][0]['content'] == '第 10 条'
    assert captured['history'][-1]['content'] == '我想去杭州玩两天，轻松一点'
