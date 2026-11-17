"""公开面脱敏：广场与公开复制不能带走精确日期、住宿地址、AI 对话。"""
from backend.services.privacy import REDACTED_ADDRESS, is_lodging_place, redact_public_trip


def _trip_data():
    return {
        'request': {'city': '杭州', 'start_date': '2027-03-15', 'travelers': 2},
        'conversation': [{'role': 'user', 'content': '同行人张三，住西湖国宾馆'}],
        'days': [{
            'stops': [
                {'place': {'name': '杭州西湖国宾馆', 'address': '西湖区杨公堤18号', 'city': '杭州'}, 'duration': 60},
                {'place': {'name': '浙江省博物馆', 'address': '孤山路25号', 'city': '杭州'}, 'duration': 90},
            ],
            'start_time': '09:00',
        }],
        'backlog': [{'place': {'name': '西溪民宿', 'address': '余杭区某某路1号', 'city': '杭州'}, 'duration': 45}],
    }


def test_lodging_detection_uses_name_hints():
    assert is_lodging_place({'name': '杭州西湖国宾馆'})
    assert is_lodging_place({'name': '西溪民宿'})
    assert not is_lodging_place({'name': '浙江省博物馆'})
    assert not is_lodging_place(None)


def test_redact_public_trip_hides_date_lodging_address_and_conversation():
    data = _trip_data()
    out = redact_public_trip(data)
    assert out['request']['start_date'] is None
    hotel, museum = out['days'][0]['stops']
    assert hotel['place']['address'] == f'杭州{REDACTED_ADDRESS}'
    assert museum['place']['address'] == '孤山路25号', '非住宿地点保留精确地址'
    assert out['backlog'][0]['place']['address'] == f'杭州{REDACTED_ADDRESS}'
    assert out['conversation'] == []
    # 深拷贝：调用方的原始数据不能被改掉，否则公开操作可能污染私有行程。
    assert data['request']['start_date'] == '2027-03-15'
    assert data['conversation']
