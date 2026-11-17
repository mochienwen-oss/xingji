from tests.conftest import login
from backend.services import planning

def test_discover_nearby_and_city_fallback(client, monkeypatch):
    from backend.services import amap
    c, places = client
    async def nearby(lon, lat, radius):
        assert (lon, lat, radius) == (110.3, 25.3, 3000)
        return places
    async def center(city):
        return {'lon':110.3, 'lat':25.3, 'city':city} if city == '桂林' else None
    monkeypatch.setattr(amap, 'discover_nearby', nearby)
    monkeypatch.setattr(amap, 'city_center', center)
    response = c.get('/api/discover/nearby', params={'lon':110.3,'lat':25.3,'radius':3000})
    assert response.status_code == 200 and response.json()[0]['id'] == places[0]['id']
    assert c.get('/api/discover/nearby', params={'lon':110.3,'lat':25.3,'radius':50000}).status_code == 422
    assert c.get('/api/discover/city-center', params={'city':'桂林'}).json()['lat'] == 25.3
    assert c.get('/api/discover/city-center', params={'city':'不存在'}).status_code == 404

def test_guest_can_plan_but_cannot_access_saved_trips(client, monkeypatch):
    c, places = client
    async def chat(messages, current, on_reply=None):
        return {'reply':'安排几天？', 'updates':{'city':'桂林'}, 'place_keywords':[]}
    monkeypatch.setattr(planning, 'planning_chat', chat)
    assert c.get('/api/places', params={'city':'桂林','q':'景点'}).json()[0]['id'] == places[0]['id']
    response = c.post('/api/planning/chat', json={'messages':[{'role':'user','content':'我想去桂林'}]})
    assert response.status_code == 200 and response.json()['updates']['city'] == '桂林'
    assert c.get('/api/trips').status_code == 401
    assert c.post('/api/trips', json={'city':'桂林','days':1}).status_code == 401

def test_login_trip_edit_save_and_user_isolation(client):
    c, places = client
    assert c.get('/api/trips').status_code == 401
    assert login(c, password='wrong').status_code == 401
    assert login(c).status_code == 200
    r = c.post('/api/trips', json={'city':'杭州', 'days':2})
    assert r.status_code == 201
    trip = r.json()
    assert len(trip['days']) == 2
    trip['days'][0]['stops'].append({'place':places[2], 'duration':60, 'reason':''})
    saved = c.put(f"/api/trips/{trip['id']}/days", json={'days':trip['days']})
    assert saved.status_code == 200
    assert saved.json()['days'][0]['routes'][0]['duration'] == 600
    assert len(c.get(f"/api/trips/{trip['id']}").json()['days'][0]['stops']) == 2
    duplicate = saved.json()['days']
    duplicate[1]['stops'].append(duplicate[0]['stops'][0])
    assert c.put(f"/api/trips/{trip['id']}/days", json={'days':duplicate}).status_code == 422
    assert login(c, 'bob', 'password2').status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404
    assert c.get('/api/trips').json() == []

def test_bad_token_and_invalid_request(client):
    c, _ = client
    c.cookies.set('trip_session', 'not-valid-base64!')
    assert c.get('/api/me').status_code == 401
    login(c)
    assert c.post('/api/trips', json={'city':'杭州', 'days':6}).status_code == 422

def test_planning_chat_updates_form_and_rejects_invalid_days(client, monkeypatch):
    c, _ = client
    login(c)
    async def chat(messages, current, on_reply=None):
        return {'reply':'安排几天？', 'updates':{'city':'桂林', 'days':3, 'unexpected':'ignored'}}
    monkeypatch.setattr(planning, 'planning_chat', chat)
    r = c.post('/api/planning/chat', json={'messages':[{'role':'user','content':'桂林三天'}]})
    assert r.status_code == 200
    assert r.json()['updates'] == {'city':'桂林','days':3}
    async def invalid(messages, current, on_reply=None):
        return {'reply':'好的', 'updates':{'days':10}}
    monkeypatch.setattr(planning, 'planning_chat', invalid)
    assert c.post('/api/planning/chat', json={'messages':[{'role':'user','content':'十天'}]}).status_code == 422

def test_chat_adjustment_is_preview_and_private(client, monkeypatch):
    c, _ = client
    login(c)
    original = c.post('/api/trips', json={'city':'桂林','days':2}).json()
    async def keywords(message, days, backlog=None): return []
    seen = {}
    async def adjust(request, candidates, instruction, current_days, backlog=None, **kwargs):
        seen.update(kwargs)
        return {'days':[{'stops':[{'place':candidates[1], 'duration':45, 'reason':'调整'}]}, {'stops':[{'place':candidates[0], 'duration':90, 'reason':''}]}], 'reply':'预览', 'changed':True}
    monkeypatch.setattr(planning, 'adjustment_keywords', keywords)
    monkeypatch.setattr(planning, 'suggest_edits', adjust)
    response = c.post(f"/api/trips/{original['id']}/assistant", json={'message':'交换两天的行程'})
    assert response.status_code == 200
    assert response.json()['days'][0]['stops'][0]['place']['id'] == original['days'][1]['stops'][0]['place']['id']
    assert seen['mode'] == 'trip' and seen['trip_id'] == original['id']
    assert c.get(f"/api/trips/{original['id']}").json()['days'] == original['days']
    conversation = c.get(f"/api/trips/{original['id']}").json()['conversation']
    assert [item['content'] for item in conversation] == ['交换两天的行程', '预览']
    login(c, 'bob', 'password2')
    assert c.post(f"/api/trips/{original['id']}/assistant", json={'message':'交换'}).status_code == 404

def test_planning_conversation_follows_created_trip(client):
    c, _ = client
    login(c)
    conversation = [{'role':'user', 'content':'桂林玩一天'}, {'role':'assistant', 'content':'想去哪些地方？'}]
    response = c.post('/api/trips', json={'city':'桂林','days':1,'conversation':conversation})
    assert response.status_code == 201
    trip = response.json()
    assert trip['conversation'] == conversation
    assert 'conversation' not in trip['request']
    assert c.get(f"/api/trips/{trip['id']}").json()['conversation'] == conversation
    login(c, 'bob', 'password2')
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404

def test_backlog_save_move_and_legacy_compatibility(client):
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    stop = {'place':places[2], 'duration':90, 'reason':'', 'activity':'参观展览'}
    r = c.put(f"/api/trips/{trip['id']}/days", json={'days':trip['days'], 'backlog':[stop]})
    assert r.status_code == 200
    assert r.json()['backlog'][0]['place']['id'] == places[2]['id']
    assert r.json()['backlog'][0]['activity'] == '参观展览'
    days = r.json()['days']
    days[0]['stops'].append(r.json()['backlog'][0])
    duplicate = c.put(f"/api/trips/{trip['id']}/days", json={'days':days})
    assert duplicate.status_code == 422
    moved = c.put(f"/api/trips/{trip['id']}/days", json={'days':days,'backlog':[]})
    assert moved.status_code == 200
    assert moved.json()['backlog'] == []
    assert moved.json()['days'][0]['stops'][-1]['activity'] == '参观展览'

def test_guide_results_are_not_saved_before_confirmation(client, monkeypatch):
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    async def extract(text): return [{'name':'象鼻山','day_hint':'第一天'}]
    monkeypatch.setattr(planning, 'guide_places', extract)
    r = c.post(f"/api/trips/{trip['id']}/guide",json={'text':'第一天去象鼻山'})
    assert r.status_code == 200
    assert r.json()['results'][0]['matches'][0]['id'] == places[0]['id']
    assert c.get(f"/api/trips/{trip['id']}").json()['backlog'] == []


def test_day_time_persists_and_old_clients_preserve_it(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    days = trip['days']
    days[0].update(start_time='09:30', end_time='18:00')
    saved = c.put(f"/api/trips/{trip['id']}/days", json={'days':days, 'version':trip['version']})
    assert saved.status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").json()['days'][0]['start_time'] == '09:30'
    legacy_days = [{'stops':saved.json()['days'][0]['stops']}]
    legacy = c.put(f"/api/trips/{trip['id']}/days", json={'days':legacy_days})
    assert legacy.json()['days'][0]['end_time'] == '18:00'
    invalid = [{'stops':legacy_days[0]['stops'], 'start_time':'25:00'}]
    assert c.put(f"/api/trips/{trip['id']}/days", json={'days':invalid}).status_code == 422
    clear = [{'stops':legacy_days[0]['stops'], 'start_time':None, 'end_time':None}]
    assert c.put(f"/api/trips/{trip['id']}/days", json={'days':clear}).json()['days'][0]['start_time'] is None


def test_fixed_time_survives_legacy_edit_and_can_be_cleared(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    days = trip['days']
    days[0]['stops'][0].update(fixed_time='10:30', fixed_next_day=True)
    saved = c.put(f"/api/trips/{trip['id']}/days", json={'days':days, 'version':trip['version']})
    assert saved.status_code == 200
    old_stop = {k:v for k,v in saved.json()['days'][0]['stops'][0].items() if k not in ('fixed_time','fixed_next_day')}
    legacy = c.put(f"/api/trips/{trip['id']}/days", json={'days':[{'stops':[old_stop]}]})
    assert legacy.json()['days'][0]['stops'][0]['fixed_time'] == '10:30'
    assert legacy.json()['days'][0]['stops'][0]['fixed_next_day'] is True
    old_stop.update(fixed_time=None, fixed_next_day=False)
    cleared = c.put(f"/api/trips/{trip['id']}/days", json={'days':[{'stops':[old_stop]}]})
    assert cleared.json()['days'][0]['stops'][0]['fixed_time'] is None


def test_nearby_requires_saved_anchor_and_owner(client, monkeypatch):
    from backend.services import amap
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    calls = []
    async def nearby(city, location, category):
        calls.append((city, location, category))
        return [places[2]]
    monkeypatch.setattr(amap, 'nearby_places', nearby)
    url=f"/api/trips/{trip['id']}/days/0/nearby"
    result=c.get(url,params={'place_id':places[0]['id'],'category':'餐厅'})
    assert result.status_code == 200 and result.json()[0]['id'] == places[2]['id']
    assert calls == [('桂林',places[0]['location'],'餐厅')]
    assert c.get(url,params={'place_id':'unknown','category':'餐厅'}).status_code == 404
    assert c.get(url,params={'place_id':places[0]['id'],'category':'unknown'}).status_code == 422
    login(c,'bob','password2')
    assert c.get(url,params={'place_id':places[0]['id'],'category':'餐厅'}).status_code == 404


def test_read_only_share_can_be_revoked_and_excludes_private_data(client):
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1,'budget':'private-budget',
        'conversation':[{'role':'user','content':'private-chat'}]}).json()
    saved = c.put(f"/api/trips/{trip['id']}/days",json={'days':trip['days'],
        'backlog':[{'place':places[2],'duration':90,'reason':'private-backlog'}],'version':trip['version']})
    assert saved.status_code == 200
    token=c.post(f"/api/trips/{trip['id']}/share").json()['token']
    login(c,'bob','password2')
    assert c.delete(f"/api/trips/{trip['id']}/share").status_code == 404
    c.post('/api/logout')
    view=c.post('/api/shares/view',json={'token':token})
    assert view.status_code == 200 and view.headers['cache-control'] == 'no-store'
    assert view.json()['id'] == trip['id'] and view.json()['is_public'] is False
    assert view.json()['city'] == '桂林' and len(view.json()['days']) == 1
    assert view.json()['owner'] == 'alice'
    assert all(secret not in view.text for secret in ('private-budget','private-chat','private-backlog','password_hash'))
    assert c.put(f"/api/trips/{trip['id']}/days",json={'days':trip['days']}).status_code == 401
    login(c)
    assert c.delete(f"/api/trips/{trip['id']}/share").status_code == 200
    assert c.post('/api/shares/view',json={'token':token}).status_code == 404


def test_update_start_date_keeps_days_and_checks_version(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 2}).json()
    resp = c.put(f"/api/trips/{trip['id']}/start-date",
                 json={'start_date': '2027-04-03', 'version': trip['version']})
    assert resp.status_code == 200
    body = resp.json()
    assert body['request']['start_date'] == '2027-04-03'
    assert body['version'] == trip['version'] + 1
    assert len(body['days']) == 2
    assert body['last_edited_by'] == 'alice'
    stale = c.put(f"/api/trips/{trip['id']}/start-date",
                  json={'start_date': '2027-05-01', 'version': trip['version']})
    assert stale.status_code == 409
    cleared = c.put(f"/api/trips/{trip['id']}/start-date",
                    json={'start_date': None, 'version': body['version']})
    assert cleared.status_code == 200 and cleared.json()['request']['start_date'] is None
    assert c.put(f"/api/trips/{trip['id']}/start-date",
                 json={'start_date': '2027-02-30', 'version': cleared.json()['version']}).status_code == 422
    c.post('/api/logout')
    assert c.put(f"/api/trips/{trip['id']}/start-date", json={'start_date': None}).status_code == 401


def test_trip_version_probe_does_not_refresh_amap(client, monkeypatch):
    from backend.services import amap
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    calls = []
    async def counted(ids):
        calls.append(list(ids))
        return {}
    monkeypatch.setattr(amap, 'find_places', counted)
    version = c.get(f"/api/trips/{trip['id']}/version")
    assert version.status_code == 200 and version.json() == {'version': trip['version']}
    assert calls == []
    assert c.get(f"/api/trips/{trip['id']}").status_code == 200
    assert calls, '完整详情仍应刷新地点'


def test_ai_backlog_move_is_preview_until_saved(client, monkeypatch):
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city':'桂林','days':1}).json()
    saved = c.put(f"/api/trips/{trip['id']}/days",json={'days':trip['days'],
        'backlog':[{'place':places[2],'duration':60,'reason':'','activity':'展览'}], 'version':trip['version']}).json()
    async def keywords(message, days, backlog=None): return []
    async def model(messages, max_tokens=4000):
        return {'reply':'建议安排','actions':[{'type':'plan','place_id':places[2]['id'],'day':1,'position':2}]}
    monkeypatch.setattr(planning, 'adjustment_keywords', keywords)
    monkeypatch.setattr(planning, 'model_json', model)
    response=c.post(f"/api/trips/{trip['id']}/assistant",json={'message':'把待规划地点安排到第一天','version':saved['version']})
    assert response.status_code == 200
    proposal=response.json()
    assert proposal['backlog'] == [] and proposal['days'][0]['stops'][1]['activity'] == '展览'
    original=c.get(f"/api/trips/{trip['id']}").json()
    assert len(original['days'][0]['stops']) == 1 and len(original['backlog']) == 1
    applied=c.put(f"/api/trips/{trip['id']}/days",json={'days':proposal['days'],'backlog':proposal['backlog'],'version':proposal['version']})
    assert applied.status_code == 200 and applied.json()['backlog'] == []


def test_planning_chat_shows_verified_map_candidates_and_handles_map_failure(client, monkeypatch):
    from backend.services import amap
    from backend.services.errors import ServiceError
    c, places = client
    login(c)
    async def chat(messages, current, on_reply=None):
        return {'reply':'可以参考这些地点','updates':{'city':'桂林'},'place_keywords':['景点']}
    monkeypatch.setattr(planning, 'planning_chat', chat)
    result=c.post('/api/planning/chat',json={'messages':[{'role':'user','content':'推荐桂林景点'}]})
    assert result.status_code == 200 and result.json()['place_matches'][0]['matches'][0]['id'] == places[0]['id']
    async def fail(city, keyword): raise ServiceError('map unavailable')
    monkeypatch.setattr(amap, 'search_places', fail)
    result=c.post('/api/planning/chat',json={'messages':[{'role':'user','content':'推荐桂林景点'}]})
    assert result.status_code == 200 and result.json()['place_notice']


def test_collected_places_are_verified_and_unplanned_ones_retained(client):
    c, places = client
    login(c)
    response=c.post('/api/trips',json={'city':'桂林','days':1,'initial_places':[places[2],places[3]]})
    assert response.status_code == 201
    result=response.json()
    assert result['days'][0]['stops'][0]['place']['id'] == places[2]['id']
    assert result['backlog'][0]['place']['id'] == places[3]['id']
    assert 'initial_places' not in result['request']
    invalid={**places[2], 'id':'not-in-map'}
    assert c.post('/api/trips',json={'city':'桂林','days':1,'initial_places':[invalid]}).status_code == 422

