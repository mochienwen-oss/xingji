"""对外令牌的唯一实现：分享链接、协作邀请、账号邮件 token 共用 backend/services/tokens.py。

需求（CHANGELOG 0.3.0「统一分享/邀请/账号 token 与 session cookie」）：三类令牌必须走同一套
生成与哈希规则，避免某一条路径的熵或哈希算法悄悄漂移；库表只存 sha256 十六进制，明文只
出现在创建响应或邮件链接里。这里既校验工具函数本身，也校验真实端点落库的哈希确实由它产生。
"""
import hashlib

from sqlalchemy import select

import backend.db as app_db
from backend.db import ShareLink, TripInvite
from backend.services import account_tokens, tokens
from tests.conftest import login

URLSAFE = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')


def test_new_token_is_url_safe_and_at_least_256_bit_by_default():
    token = tokens.new_token()
    assert token == token.strip()
    assert set(token) <= URLSAFE, token
    assert len(token) >= 43, '32 字节 base64url（无填充）至少 43 个字符'


def test_new_token_is_random_and_honours_requested_bytes():
    assert len({tokens.new_token(24) for _ in range(20)}) == 20
    assert len(tokens.new_token(24)) >= 32, '邀请令牌沿用 24 字节配置'
    assert (tokens.SHARE_BYTES, tokens.INVITE_BYTES, tokens.ACCOUNT_BYTES) == (32, 24, 32)


def test_hash_token_is_sha256_hex_of_utf8():
    assert tokens.hash_token('token') == hashlib.sha256('token'.encode('utf-8')).hexdigest()
    assert len(tokens.hash_token('token')) == 64
    assert tokens.hash_token('token') != tokens.hash_token('Token'), '大小写敏感'


def test_account_tokens_reuses_the_shared_hash():
    # account_tokens 仍 re-export hash_token（既有调用方/测试），但必须是同一个实现。
    assert account_tokens.hash_token is tokens.hash_token


def test_share_endpoint_stores_shared_hash_of_returned_plaintext(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']

    with app_db.Session() as db:
        rows = db.scalars(select(ShareLink).where(ShareLink.trip_id == trip['id'])).all()
    assert len(rows) == 1
    assert rows[0].token_hash == tokens.hash_token(token)
    # 端点接受留存的哈希，证明明文确实没有落库。
    assert c.post('/api/shares/view', json={'token': token}).status_code == 200


def test_invite_endpoint_stores_shared_hash_and_accepts_the_plaintext(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    token = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']

    with app_db.Session() as db:
        invite = db.scalar(select(TripInvite).where(TripInvite.trip_id == trip['id']))
    assert invite is not None
    assert invite.token_hash == tokens.hash_token(token)

    login(c, 'bob', 'password2')
    accepted = c.post('/api/collaborators/accept', json={'token': token})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['trip_id'] == trip['id']
