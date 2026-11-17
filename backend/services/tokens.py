"""对外一次性令牌的唯一实现：分享链接、协作邀请与账号邮件 token 共用。

约定：
- 库表只存 sha256 十六进制（列统一 String(64)），明文只在创建响应或邮件链接里出现；
- 字节长度沿用既有值（分享 32、邀请 24、账号 32），避免已发出链接的长度/格式变化。
"""
import hashlib
import secrets

SHARE_BYTES = 32
INVITE_BYTES = 24
ACCOUNT_BYTES = 32


def new_token(nbytes: int = SHARE_BYTES) -> str:
    """生成 URL-safe 明文 token。"""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """落库用的 sha256 十六进制；查询时直接与 token_hash 列等值匹配。"""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
