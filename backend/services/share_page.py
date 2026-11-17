"""分享链接的落地页（可被爬虫抓取的最小 HTML）。

前端是单页应用，分享链接原本是 /#share=<token>：浏览器能打开，但微信、X 等
抓取器不会执行 JS，也看不到 hash 后面的内容，链接永远只有站点默认标题。
这里在服务端直出一个极简 HTML，把标题、描述、封面写进 OG/Twitter 标签，
再把真人浏览器重定向回互动版分享页。

隐私取舍：分享 token 本身就是访问凭据，页面显式 noindex,follow，
不生成 sitemap，也不调用高德（落地页不产生外部成本和额外延迟）。
"""
import html
import json
from urllib.parse import quote

from ..db import Trip
from . import site_config

SITE_NAME = '行迹 Trip'
TITLE_MAX = 70
DESCRIPTION_MAX = 120


def _trip_meta(trip: Trip) -> tuple[str, str, int]:
    """从行程 JSON 里取分享所需的公开摘要，不刷新地点、不读预算/对话。"""
    try:
        data = json.loads(trip.data or '{}')
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    request = data.get('request') if isinstance(data.get('request'), dict) else {}
    days_list = data.get('days') if isinstance(data.get('days'), list) else []
    city = str(request.get('city') or trip.city or '').strip()
    days = request.get('days')
    if not isinstance(days, int) or days <= 0:
        days = len(days_list)
    stops = 0
    for day in days_list:
        if isinstance(day, dict) and isinstance(day.get('stops'), list):
            stops += len(day['stops'])
    title = (trip.title or '').strip() or (f'{city}旅行计划' if city else '旅行计划')
    parts = []
    if days:
        parts.append(f'{days} 天')
    if stops:
        parts.append(f'{stops} 个地点')
    if city:
        parts.append(city)
    description = ' · '.join(parts) + '，来自行迹 Trip 的可编辑行程。' if parts else '来自行迹 Trip 的可编辑行程。'
    return title[:TITLE_MAX], description[:DESCRIPTION_MAX], stops


def _shell(title: str, description: str, canonical: str, app_url: str, og_title: str) -> str:
    base = site_config.base_url()
    image = f'{base}/og-cover.png'
    # 所有变量都经过 html.escape；app_url 同时以 JSON 形式进内联脚本，避免引号截断。
    script_url = json.dumps(app_url, ensure_ascii=False).replace('</', '<\\/')
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}" />
<meta name="robots" content="noindex,follow" />
<link rel="canonical" href="{html.escape(canonical)}" />
<meta property="og:site_name" content="{SITE_NAME}" />
<meta property="og:type" content="article" />
<meta property="og:title" content="{html.escape(og_title)}" />
<meta property="og:description" content="{html.escape(description)}" />
<meta property="og:url" content="{html.escape(canonical)}" />
<meta property="og:image" content="{html.escape(image)}" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:locale" content="zh_CN" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{html.escape(og_title)}" />
<meta name="twitter:description" content="{html.escape(description)}" />
<meta name="twitter:image" content="{html.escape(image)}" />
<meta name="theme-color" content="#f5f3ec" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100dvh; display: grid; place-items: center; padding: 24px;
  background: #f5f3ec; color: #20382a;
  font-family: "Noto Serif SC", "Songti SC", serif; }}
main {{ width: min(560px, 100%); }}
p.brand {{ margin: 0 0 28px; font-size: 12px; letter-spacing: .18em; text-transform: uppercase; color: #53665a;
  font-family: system-ui, sans-serif; }}
h1 {{ margin: 0 0 14px; font-size: clamp(28px, 7vw, 44px); line-height: 1.2; font-weight: 600; }}
p.desc {{ margin: 0 0 32px; font-size: 15px; line-height: 1.8; color: #53665a; }}
a.cta {{ display: inline-flex; min-height: 48px; align-items: center; justify-content: center; padding: 0 28px;
  border-radius: 999px; background: #20382a; color: #fffefa; text-decoration: none; font-size: 15px;
  font-family: system-ui, sans-serif; }}
a.cta:focus-visible {{ outline: 2px solid #A8342A; outline-offset: 3px; }}
p.hint {{ margin: 18px 0 0; font-size: 12px; color: #5f6b63; font-family: system-ui, sans-serif; }}
</style>
</head>
<body>
<main>
  <p class="brand">行迹 TRIP · 只读分享</p>
  <h1>{html.escape(title)}</h1>
  <p class="desc">{html.escape(description)}</p>
  <a class="cta" href="{html.escape(app_url)}">打开互动行程</a>
  <p class="hint">正在打开互动版…如果页面没有自动跳转，请点上面的按钮。</p>
</main>
<script>location.replace({script_url});</script>
</body>
</html>
'''


def render_share_page(trip: Trip, token: str) -> str:
    title, description, _stops = _trip_meta(trip)
    base = site_config.base_url()
    canonical = f'{base}/s/{quote(token, safe="")}'
    app_url = f'{base}/#share={quote(token, safe="")}'
    og_title = f'{title} · {SITE_NAME}'
    return _shell(title, description, canonical, app_url, og_title)


def render_not_found() -> str:
    title = '分享不存在或已撤销 · 行迹 Trip'
    description = '这条分享链接已失效。你可以打开行迹，规划自己的行程。'
    base = site_config.base_url()
    return _shell(title, description, f'{base}/', f'{base}/', title)
