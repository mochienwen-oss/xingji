import json

from backend.services import share_page, trip_places
from tests.conftest import login


def test_share_landing_has_og_tags_and_skips_amap(client, monkeypatch):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 2, 'budget': 'private-budget',
                                      'conversation': [{'role': 'user', 'content': 'private-chat'}]}).json()
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']

    async def boom(*_args, **_kwargs):
        raise AssertionError('分享落地页不能刷新高德')

    monkeypatch.setattr(trip_places, 'refresh', boom)
    page = c.get(f'/s/{token}')
    assert page.status_code == 200
    assert page.headers['content-type'].startswith('text/html')
    assert page.headers['cache-control'] == 'no-store'
    body = page.text
    assert '<meta property="og:title"' in body
    assert '杭州' in body
    assert '个地点' in body
    assert f'/s/{token}' in body
    assert '#share=' in body
    assert 'noindex,follow' in body
    assert 'og-cover.png' in body
    # 分享页只读公开摘要，不能泄露预算/对话。
    assert 'private-budget' not in body and 'private-chat' not in body


def test_share_landing_404_after_revoke(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    assert c.get(f'/s/{token}').status_code == 200
    assert c.delete(f"/api/trips/{trip['id']}/share").status_code == 200
    page = c.get(f'/s/{token}')
    assert page.status_code == 404
    assert '分享不存在或已撤销' in page.text
    assert 'noindex' in page.text
    assert c.get('/s/not-a-real-token').status_code == 404


def test_share_landing_escapes_title():
    class FakeTrip:
        data = json.dumps({'request': {'city': '杭州', 'days': 1},
                           'days': [{'stops': [{'place': {'name': '西湖'}}]}]})
        title = '<script>alert(1)</script>'
        city = '杭州'

    body = share_page.render_share_page(FakeTrip(), 'tok')
    assert '<script>alert(1)</script>' not in body
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in body


def test_robots_disallows_share_paths(client):
    c, _ = client
    page = c.get('/robots.txt')
    assert page.status_code == 200
    assert 'Disallow: /s/' in page.text
    assert 'Disallow: /api/' in page.text
    assert 'Sitemap:' in page.text and '/sitemap.xml' in page.text
    sitemap = c.get('/sitemap.xml')
    assert sitemap.status_code == 200
    assert sitemap.headers['content-type'].startswith('application/xml')
    assert '<loc>' in sitemap.text and '<urlset' in sitemap.text
