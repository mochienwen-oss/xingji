"""限流规则表的可见契约：关键路径必须命中自己的专用档位。

为什么单独测规则表：ratelimit.match() 遍历 RULES 并在**第一条命中处**返回，所以列表顺序
就是语义。0.3.0「补全限流覆盖」在 /api/shares/view（30 突发、每 2s 补 1）和
/api/shares/fork（6 突发、每 30s 补 1）之前插入了一条更宽的 ^/api/shares/[^/]+$
（60 突发、每 3s 补 1），于是两条专用规则永远轮不到——匿名 fork 的突发上限被悄悄放宽了
10 倍。预期档位取自既有产品约定与各规则注释，
不是从当前实现抄回去的。

这些断言只在「规则表」层面校验语义，不依赖 sleep：真正被用户感知的是端点上的 429，
所以下面还有一个走完整 HTTP 链路的突发测试。
"""
import pytest

from backend.services import ratelimit
from tests.conftest import login

# 路径 -> (突发容量, 每秒补充的令牌数)
EXPECTED = {
    # 分享入口：view 要读全量行程，fork 会写一份副本，比通用的 /api/shares/{token} 更紧。
    '/api/shares/view': (30, 1 / 2),
    '/api/shares/fork': (6, 1 / 30),
    '/api/shares/abcdefgh': (60, 1 / 3),
    # 公开落地页：渲染整页 HTML，需求要求匿名入口都有档位（审计 P1-G3）。
    '/s/abcdefgh': (60, 1 / 2),
    '/api/shares/abcdefgh/report': (3, 1 / 3600),
    # 协作与分享码：8 位码仍可能与码空间擦肩，必须收紧。
    '/api/trips/join': (5, 1 / 30),
    '/api/trips/shared': (30, 1 / 2),
    '/api/trips/7/join-code': (20, 1 / 10),
    '/api/trips/7/visibility': (20, 1 / 10),
    '/api/trips/7/restore': (10, 1 / 30),
    '/api/trips/7/share': (20, 1 / 10),
    '/api/trips/7/expenses': (30, 1 / 5),
    # 会烧外部接口或 LLM 额度的路径。
    '/api/trips/7/days': (30, 1 / 2),
    '/api/trips/7/days/0/optimize': (10, 1 / 6),
    '/api/trips/7/assistant/stream': (20, 1 / 3),
    '/api/trips/from-preview': (6, 1 / 10),
    '/api/planning/session/stream': (10, 1 / 6),
    '/api/account/export': (3, 1 / 60),
    '/api/login': (10, 1 / 60),
}


@pytest.mark.parametrize('path,expected', sorted(EXPECTED.items()))
def test_key_paths_hit_their_dedicated_rule(path, expected):
    rule = ratelimit.match(path)
    assert rule is not None, f'{path} 必须受限流覆盖'
    assert (rule.capacity, rule.rate) == pytest.approx(expected), (
        f'{path} 命中了 {rule.pattern.pattern}（容量 {rule.capacity}、'
        f'每 {1 / rule.rate:.0f}s 补 1），不是它自己的档位 '
        f'（容量 {expected[0]}、每 {1 / expected[1]:.0f}s 补 1）——'
        '更宽的规则插在了前面，遮蔽了专用规则'
    )


def test_broader_rule_does_not_shadow_specific_rule():
    """回归：^/api/shares/{token} 这条通用规则不能排在 view/fork 之前。

    需求：/api/shares/view 30 次/2s、
    /api/shares/fork 6 次/30s。若通用规则先命中，两者的实际档位退化成 60 次/3s。
    """
    generic = next(rule for rule in ratelimit.RULES
                   if rule.pattern.pattern == r'^/api/shares/[^/]+$')
    view = ratelimit.match('/api/shares/view')
    fork = ratelimit.match('/api/shares/fork')
    assert view is not generic, '/api/shares/view 被通用分享规则遮蔽了'
    assert fork is not generic, '/api/shares/fork 被通用分享规则遮蔽了'
    # 通用规则仍然要覆盖真正的 /api/shares/{token} 路径（撤销单条分享）。
    assert ratelimit.match('/api/shares/sometoken') is generic

def test_fork_burst_is_cut_off_at_its_own_capacity(client):
    """用户可见契约：同一台设备连续复制行程，第 7 次必须被 429 拦住。

    需求出处同上（fork 6 次/30s）。走真实 HTTP 链路，能同时覆盖中间件顺序与规则表。
    """
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']

    login(c, 'bob', 'password2')
    statuses = [c.post('/api/shares/fork', json={'token': token}).status_code for _ in range(7)]
    assert statuses[:6] == [201] * 6, statuses
    assert statuses[6] == 429, statuses
    assert c.post('/api/shares/fork', json={'token': token}).headers['Retry-After']


def test_public_share_page_burst_is_limited(client):
    """用户可见契约：匿名刷分享落地页，第 61 次必须 429。

    需求（0.3.0 限流覆盖）：分享落地页是匿名入口，不能成为无上限的渲染/磁盘读放大器。
    前 60 次允许 404（token 不存在）等业务响应，但不能出现 429；第 61 次必须是 429。
    """
    c, _ = client
    statuses = [c.get('/s/does-not-exist').status_code for _ in range(61)]
    assert 429 not in statuses[:60], statuses
    assert statuses[60] == 429, statuses
    assert int(c.get('/s/does-not-exist').headers['Retry-After']) >= 1
