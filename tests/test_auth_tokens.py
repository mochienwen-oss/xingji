"""B1/D3：会话 token 带 session_version 与会话盐，并兼容旧格式 token。"""
import base64
import hashlib
import hmac
import time

from backend import auth


def _sign(payload: str) -> str:
    """按现有算法签名并整体 base64：用来手工构造旧格式/过期 token。"""
    sig = hmac.new(auth.SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f'{payload}:{sig}'.encode()).decode()


def _legacy_token(user_id: int, expires: int) -> str:
    return _sign(f'{user_id}:{expires}')


def test_make_token_defaults_to_version_zero_and_empty_nonce():
    assert auth.read_token(auth.make_token(7)) == (7, 0, '')


def test_make_token_round_trips_session_version_and_nonce():
    assert auth.read_token(auth.make_token(7, 3, 'abc123')) == (7, 3, 'abc123')


def test_make_token_payload_carries_five_segments():
    token = auth.make_token(7, 3, 'abc123')
    uid, expires, version, nonce, sig = base64.urlsafe_b64decode(token.encode()).decode().split(':')
    assert (uid, version, nonce) == ('7', '3', 'abc123')
    assert int(expires) > time.time()
    assert len(sig) == 64


def test_legacy_three_segment_token_reads_as_version_zero():
    assert auth.read_token(_legacy_token(7, int(time.time()) + 60)) == (7, 0, '')


def test_four_segment_token_reads_with_empty_nonce():
    """session_version 刚上线时的四段 cookie 没有盐，按空 nonce 兼容。"""
    expires = int(time.time()) + 60
    assert auth.read_token(_sign(f'7:{expires}:3')) == (7, 3, '')


def test_tampered_signature_returns_none():
    raw = base64.urlsafe_b64decode(auth.make_token(7, 3, 'abc123').encode()).decode()
    uid, expires, version, nonce, _sig = raw.split(':')
    tampered = base64.urlsafe_b64encode(f'{uid}:{expires}:{version}:{nonce}:{"0" * 64}'.encode()).decode()
    assert auth.read_token(tampered) is None
    # 改 nonce 但沿用原签名同样应被拒绝
    resigned = base64.urlsafe_b64encode(f'{uid}:{expires}:{version}:other:{_sig}'.encode()).decode()
    assert auth.read_token(resigned) is None


def test_expired_token_returns_none():
    assert auth.read_token(_sign(f'7:{int(time.time()) - 1}:0')) is None


def test_expired_legacy_token_returns_none():
    assert auth.read_token(_legacy_token(7, int(time.time()) - 1)) is None


def test_malformed_tokens_return_none():
    garbage = [
        '',
        'not-valid-base64!',
        base64.urlsafe_b64encode(b'garbage').decode(),
        base64.urlsafe_b64encode(b'1:2:3:4:5:sig').decode(),
        auth.make_token(7)[:-4],
    ]
    for token in garbage:
        assert auth.read_token(token) is None
