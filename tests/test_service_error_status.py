"""P1：ServiceError 按语义返回状态码（默认 503、模型输出 502、找不到 404、配额 429）。"""
import pytest

from backend.services.errors import ModelOutputError, ServiceError
from tests.conftest import login


def _boom(exc):
    async def fail(*args, **kwargs):
        raise exc
    return fail


def test_error_defaults():
    assert str(ServiceError('文案')) == '文案'
    assert ServiceError('x').status_code == 503
    assert ModelOutputError('x').status_code == 502
    assert isinstance(ModelOutputError('x'), ServiceError)


@pytest.mark.parametrize('exc, expected', [
    (ServiceError('上游暂时不可用，请稍后重试。'), 503),
    (ModelOutputError('模型返回内容不完整或格式无效，请重试。'), 502),
    (ServiceError('没有找到地点「火星」，请换个说法。', 404), 404),
    (ServiceError('模型服务请求受限，请检查配额或稍后重试。', 429), 429),
])
def test_service_error_status_mapping(client, monkeypatch, exc, expected):
    c, _ = client
    login(c)
    monkeypatch.setattr('backend.api.trips.planning.generate_plan', _boom(exc))
    resp = c.post('/api/trips', json={'city': '杭州', 'days': 1})
    assert resp.status_code == expected, resp.text
    assert resp.json()['detail'] == str(exc)
    # 前端只读 detail；429 额外给 Retry-After，便于 UI 提示稍后重试
    assert ('Retry-After' in resp.headers) is (expected == 429)
