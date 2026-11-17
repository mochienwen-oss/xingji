import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..schemas import InspirationBody
from ..services import amap, planning

router = APIRouter()
log = logging.getLogger(__name__)

# 主题目录是固定常量，与城市无关，不需要缓存；保留 city 参数只为校验与未来按城市扩展。
_THEME_CATALOG = [
    {'id': 'citywalk', 'label': '城市漫步', 'desc': '老街巷与在地生活'},
    {'id': 'history', 'label': '历史印记', 'desc': '博物馆与老建筑'},
    {'id': 'night', 'label': '夜色探索', 'desc': '夜市与城市夜景'},
    {'id': 'market', 'label': '市集烟火', 'desc': '本地市集与小吃'},
    {'id': 'nature', 'label': '自然疗愈', 'desc': '公园绿道与山水'},
    {'id': 'art', 'label': '文艺角落', 'desc': '美术馆与独立书店'},
    {'id': 'water', 'label': '沿水而行', 'desc': '江河湖畔步道'},
    {'id': 'foodie', 'label': '觅食之旅', 'desc': '地道馆子与老字号'},
]

def _theme_catalog() -> list[dict]:
    return [dict(theme) for theme in _THEME_CATALOG]

@router.get('/api/inspiration/themes')
def inspiration_themes(city: str):
    """小众灵感主题目录；游客可用，接口本身不读写用户数据。"""
    clean = city.strip()[:40]
    if not clean:
        raise HTTPException(422, '请先选择城市。')
    return {'themes': _theme_catalog()}

@router.post('/api/inspiration')
async def inspiration_route(body: InspirationBody):
    """生成一条主题小众路线（游客可用）：AI 出骨架，地点逐个经高德实搜核对，搜不到的丢弃。

    匿名访问的模型成本由 ratelimit 对 /api/inspiration 的规则兜住。
    """
    theme = next((t for t in _theme_catalog() if t['id'] == body.theme_id), None)
    if theme:
        label, desc = theme['label'], theme['desc']
    else:
        label, desc = body.theme_label.strip(), body.theme_desc.strip()
    if not label:
        raise HTTPException(422, '请选择一个灵感主题。')
    city = body.city.strip()
    route = await planning.inspiration_route(city, label, desc)
    semaphore = asyncio.Semaphore(amap.AMAP_BATCH_CONCURRENCY)

    async def resolve(item: dict) -> tuple[dict | None, str] | None:
        """把 AI 给出的一个地点名换成高德实搜结果；搜不到/失败返回 None，不影响其余地点。"""
        if not isinstance(item, dict):
            return None
        name = item.get('name')
        if not isinstance(name, str) or not name.strip():
            return None
        try:
            async with semaphore:
                matches = await amap.search_places(city, name)
        except Exception as exc:  # 单个地点的搜索失败不该让整条主题路线 503
            log.warning('inspiration place lookup failed name=%s error=%s', name, exc)
            return None
        place = next((m for m in matches if m['name'] == name), None) or (matches[0] if matches else None)
        return (place, item.get('why', '')) if place else None

    # 各地点并发核对（限并发 4），再按 AI 给出的顺序去重，避免逐个串行等待地图接口。
    results = await asyncio.gather(*(resolve(item) for item in route['stops']))
    stops = []
    seen = set()
    for result in results:
        if not result:
            continue
        place, why = result
        if place['id'] in seen:
            continue
        seen.add(place['id'])
        stops.append({'place': place, 'why': why})
    if len(stops) < 3:
        raise HTTPException(503, '这个主题下暂时没有找到足够的小众地点，请换个主题试试。')
    return {'title': route['title'], 'intro': route['intro'], 'stops': stops}
