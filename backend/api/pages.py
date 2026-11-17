"""前端构建产物与站点静态文件路由。

页面文件只在 frontend/dist 存在时注册；开发时前端由 Vite 提供页面，后端只服务 API。
分享页带访问 token，robots.txt 明确不收录 /s/，sitemap 只收录站点根地址。
"""
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse

from ..services import site_config

router = APIRouter()
DIST = Path(__file__).resolve().parent.parent.parent / 'frontend' / 'dist'

def available() -> bool:
    return DIST.exists()

@router.get('/')
def index():
    return FileResponse(DIST / 'index.html')

@router.get('/favicon.svg', include_in_schema=False)
def favicon():
    return FileResponse(DIST / 'favicon.svg')

@router.get('/og-cover.png', include_in_schema=False)
def og_cover():
    return FileResponse(DIST / 'og-cover.png')

@router.get('/robots.txt', include_in_schema=False)
def robots():
    # 分享页带访问 token，不交给搜索引擎；公开页只有首页，sitemap 只收录根地址。
    base = site_config.base_url()
    return PlainTextResponse(
        f'User-agent: *\nDisallow: /api/\nDisallow: /s/\nAllow: /\nSitemap: {base}/sitemap.xml\n')

@router.get('/sitemap.xml', include_in_schema=False)
def sitemap():
    base = site_config.base_url()
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{xml_escape(base)}/</loc></url></urlset>')
    return PlainTextResponse(body, media_type='application/xml')
