import asyncio
import json
import logging
import os
from collections.abc import Callable
import httpx
from .env import env_float, env_int
from .errors import ModelOutputError, ServiceError
from .http_pool import shared_client

log = logging.getLogger('uvicorn.error')

# 全局并发闸门：模型调用是外部计费资源，单进程同时最多 LLM_MAX_CONCURRENCY 个在飞。
SEMAPHORE = asyncio.Semaphore(env_int('LLM_MAX_CONCURRENCY', 4, minimum=1))

# 排队上限：闸门占满时最多等这么久，随后转 503，避免请求挂到反向代理超时。
LLM_QUEUE_TIMEOUT_SECONDS = env_float('LLM_QUEUE_TIMEOUT_SECONDS', 8.0, minimum=0.0)
# 上游模型偶发 5xx/超时/限流，或返回被截断/结构残缺的内容时快速重试一次；4xx 配置错误不重试，避免把错误放大。
LLM_RETRY_ATTEMPTS = env_int('LLM_RETRY_ATTEMPTS', 2, minimum=1)
LLM_RETRY_BACKOFF_SECONDS = env_float('LLM_RETRY_BACKOFF_SECONDS', 0.6, minimum=0.0)

def _retryable_status(status: int) -> bool:
    return status in (408, 425, 429, 500, 502, 503, 504)

def _retry_delay(attempt: int) -> float:
    return min(LLM_RETRY_BACKOFF_SECONDS * (2 ** attempt), 3.0)

__all__ = ['LLM_QUEUE_TIMEOUT_SECONDS', 'ModelOutputError', 'SEMAPHORE', 'model_json']

def _reply_start(raw: str) -> int:
    """定位顶层 reply 字段字符串正文的起始下标；尚不完整时返回 -1。

    与 _ReplyStream 相同的顶层扫描方式（嵌套的 "reply" 会被 raw_decode 跳过），
    只在流式首帧/键未到齐时调用，键之后由 _ReplyStream 增量解码，避免每次
    chunk 都重新解析整段 JSON。
    """
    decoder = json.JSONDecoder()
    i = len(raw) - len(raw.lstrip())
    if i >= len(raw) or raw[i] != '{':
        return -1
    i += 1
    while i < len(raw):
        while i < len(raw) and raw[i] in ' \r\n\t,': i += 1
        try:
            key, i = decoder.raw_decode(raw, i)
        except ValueError:
            return -1
        while i < len(raw) and raw[i].isspace(): i += 1
        if i >= len(raw) or raw[i] != ':':
            return -1
        i += 1
        while i < len(raw) and raw[i].isspace(): i += 1
        if i >= len(raw):
            return -1
        if key == 'reply':
            return i + 1 if raw[i] == '"' else -1
        try:
            _, i = decoder.raw_decode(raw, i)
        except ValueError:
            return -1
    return -1


_ESCAPES = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}


def _decode_reply_prefix(body: str, pos: int) -> tuple[str, int]:
    """从 body[pos] 开始增量解码 reply 字符串，返回 (新增文本, 新位置)。

    遇到未结束的转义/高代理项时停在原处，下一个 chunk 到齐后继续；
    遇到未转义的结束引号时结束（位置指向该引号）。
    """
    out: list[str] = []
    i, size = pos, len(body)
    while i < size:
        char = body[i]
        if char == '"':
            break
        if char != '\\':
            out.append(char)
            i += 1
            continue
        if i + 1 >= size:
            break
        esc = body[i + 1]
        if esc == 'u':
            if i + 6 > size:
                break
            try:
                code = int(body[i + 2:i + 6], 16)
            except ValueError:
                break
            if 0xD800 <= code <= 0xDBFF:
                if i + 12 > size or body[i + 6:i + 8] != '\\u':
                    break
                try:
                    low = int(body[i + 8:i + 12], 16)
                except ValueError:
                    break
                if not 0xDC00 <= low <= 0xDFFF:
                    break
                out.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                i += 12
                continue
            if 0xDC00 <= code <= 0xDFFF:
                break
            out.append(chr(code))
            i += 6
            continue
        mapped = _ESCAPES.get(esc)
        if mapped is None:
            break
        out.append(mapped)
        i += 2
    return ''.join(out), i


class _ReplyStream:
    """流式 reply 提取器：只解码新增部分，整体复杂度 O(n)。"""

    def __init__(self) -> None:
        self._start = -1
        self._pos = 0
        self._decoded = ''
        self._done = False

    def feed(self, raw: str) -> str:
        if self._done:
            return self._decoded
        if self._start < 0:
            start = _reply_start(raw)
            if start < 0:
                return ''
            self._start = start
        body = raw[self._start:]
        if self._pos < len(body):
            piece, self._pos = _decode_reply_prefix(body, self._pos)
            self._decoded += piece
        if self._pos < len(body) and body[self._pos] == '"':
            self._done = True
        return self._decoded


class _shared_client:
    """共享 httpx 客户端的外壳：只借出连接池，不在退出时关闭共享池。"""

    async def __aenter__(self):
        # 模型响应可能很长，读超时放宽到 90s；连接超时仍保持较短。
        return shared_client(name='llm', timeout=httpx.Timeout(90.0, connect=10.0))

    async def __aexit__(self, *exc_info):
        return False


class _UnusableReply(ValueError):
    """响应结构缺失或 content 不可用：属于内容级失败，重试有机会恢复。"""


class _TruncatedReply(ValueError):
    """finish_reason=length：输出被 max_tokens 截断，重试有机会拿到完整回复。"""


def _choice_content(payload: object) -> tuple[str, str]:
    """校验 chat/completions 响应结构，返回 (正文, finish_reason)。"""
    if not isinstance(payload, dict):
        raise _UnusableReply('payload is not an object')
    choices = payload.get('choices')
    if not isinstance(choices, list) or not choices:
        raise _UnusableReply('choices is empty')
    choice = choices[0]
    if not isinstance(choice, dict):
        raise _UnusableReply('choice is not an object')
    message = choice.get('message')
    if not isinstance(message, dict):
        raise _UnusableReply('message is missing')
    content = message.get('content')
    if not isinstance(content, str) or not content.strip():
        raise _UnusableReply('content is not a non-empty string')
    reason = choice.get('finish_reason')
    return content, reason if isinstance(reason, str) else ''


def _unfence(text: str) -> str:
    """去掉 markdown 代码围栏，返回围栏内的正文；没有围栏时返回空串。"""
    if not text.startswith('```'):
        return ''
    body = text[3:]
    if body[:4].lower() == 'json':
        body = body[4:]
    end = body.rfind('```')
    if end >= 0:
        body = body[:end]
    return body.strip()


def _loads_reply(content: str) -> dict:
    """解析模型正文：先按 JSON 解析，再容忍代码围栏和前后说明文字，仍失败抛 ValueError。"""
    text = content.strip()
    candidates = [text]
    fenced = _unfence(text)
    if fenced:
        candidates.append(fenced)
        start, end = fenced.find('{'), fenced.rfind('}')
        if 0 <= start < end:
            candidates.append(fenced[start:end + 1])
    start, end = text.find('{'), text.rfind('}')
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(value, dict):
            raise ValueError('model reply is not a JSON object')
        return value
    raise ValueError('model reply is not valid JSON')


async def model_json(messages: list[dict], max_tokens: int = 4000, on_reply: Callable[[str], None] | None = None) -> dict:
    base_url = os.getenv('LLM_BASE_URL', '').strip().rstrip('/')
    if base_url:
        key = os.getenv('LLM_API_KEY', '').strip()
        model = os.getenv('LLM_MODEL', '').strip()
        if not key or not model:
            raise ServiceError('请配置企业模型的 LLM_API_KEY 和 LLM_MODEL。')
    else:
        base_url = 'https://api.deepseek.com'
        key = os.getenv('DEEPSEEK_API_KEY', '').strip()
        model = os.getenv('DEEPSEEK_MODEL', 'deepseek-flash').strip()
    if not key:
        raise ServiceError('尚未配置模型 API Key。')
    acquired = False
    try:
        # 排队也要限时：拿不到闸门就快速失败，不能把连接和用户一起拖到超时。
        try:
            await asyncio.wait_for(SEMAPHORE.acquire(), timeout=LLM_QUEUE_TIMEOUT_SECONDS)
            acquired = True
        except asyncio.TimeoutError as exc:
            raise ServiceError('AI 服务繁忙，请稍后重试。', 503) from exc
        # 信号量覆盖整个请求（含流式读取），只有真正拿到时才在 finally 里释放。
        # 复用 http_pool 的共享客户端：避免每次调用重建连接/TLS 会话，连接数也可控。
        async with _shared_client() as client:
            request = {
                'model': model, 'response_format': {'type': 'json_object'},
                'messages': messages, 'max_tokens': max_tokens, 'temperature': 0.3}
            raw: dict | None = None
            if on_reply is None:
                # 内容不可用（截断 JSON、缺 choices/content）同样是上游抖动，和传输错误一起重试。
                for attempt in range(LLM_RETRY_ATTEMPTS):
                    last = attempt + 1 >= LLM_RETRY_ATTEMPTS
                    chars = 0
                    try:
                        response = await client.post(f'{base_url}/chat/completions', headers={'Authorization': f'Bearer {key}'}, json=request)
                        response.raise_for_status()
                        content, finish_reason = _choice_content(response.json())
                        chars = len(content)
                        # 被 max_tokens 截断时正文必然不完整，重试有机会拿到完整输出。
                        if finish_reason == 'length':
                            raise _TruncatedReply('finish_reason=length')
                        raw = _loads_reply(content)
                        break
                    except httpx.HTTPStatusError as exc:
                        if not _retryable_status(exc.response.status_code) or last:
                            raise
                        log.warning('Model HTTP %s, retrying attempt=%d', exc.response.status_code, attempt + 1)
                    except (httpx.TransportError, httpx.TimeoutException) as exc:
                        if last:
                            raise
                        log.warning('Model transport error %s, retrying attempt=%d', type(exc).__name__, attempt + 1)
                    except _TruncatedReply as exc:
                        # 只记异常类型和正文长度，模型原文不进日志。
                        log.warning('Model reply truncated: %s attempt=%d chars=%d', type(exc).__name__, attempt + 1, chars)
                        if last:
                            raise ModelOutputError('模型输出超过长度限制，请简化旅行需求后重试。') from exc
                    except _UnusableReply as exc:
                        log.warning('Model reply unusable: %s attempt=%d chars=%d', type(exc).__name__, attempt + 1, chars)
                        if last:
                            raise ModelOutputError('模型没有返回有效内容，请重试。') from exc
                    except ValueError as exc:
                        log.warning('Model reply not valid JSON: %s attempt=%d chars=%d', type(exc).__name__, attempt + 1, chars)
                        if last:
                            raise ModelOutputError('模型返回内容不完整或格式无效，请重试。') from exc
                    await asyncio.sleep(_retry_delay(attempt))
            else:
                content, emitted, finished = '', '', False
                for attempt in range(LLM_RETRY_ATTEMPTS):
                    last = attempt + 1 >= LLM_RETRY_ATTEMPTS
                    content, finished = '', False
                    reply_stream = _ReplyStream()
                    try:
                        async with client.stream('POST', f'{base_url}/chat/completions', headers={'Authorization': f'Bearer {key}'}, json={**request, 'stream': True}) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line.startswith('data:'): continue
                                data = line[5:].strip()
                                if data == '[DONE]':
                                    finished = True
                                    break
                                if not data: continue
                                item = json.loads(data)
                                choices = item.get('choices') or []
                                if not choices: continue
                                choice = choices[0]
                                piece = (choice.get('delta') or {}).get('content') or ''
                                if not isinstance(piece, str): raise ValueError('invalid stream content')
                                content += piece
                                prefix = reply_stream.feed(content)
                                if len(prefix) > len(emitted):
                                    on_reply(prefix[len(emitted):])
                                    emitted = prefix
                                if choice.get('finish_reason') == 'length':
                                    log.warning('Model stream was truncated by the output limit')
                                    raise ModelOutputError('模型输出超过长度限制，请简化旅行需求后重试。')
                                if choice.get('finish_reason') == 'stop': finished = True
                        # 流没收尾或拼出的 JSON 不可用：只有还没给用户推过字才允许重放。
                        if not finished:
                            raise ValueError('incomplete model stream')
                        raw = _loads_reply(content)
                        break
                    except httpx.HTTPStatusError as exc:
                        # 已经给用户推过字就不能重放，否则前端会看到重复内容。
                        if emitted or not _retryable_status(exc.response.status_code) or last:
                            raise
                        log.warning('Model stream HTTP %s, retrying attempt=%d', exc.response.status_code, attempt + 1)
                    except (httpx.TransportError, httpx.TimeoutException) as exc:
                        if emitted or last:
                            raise
                        log.warning('Model stream transport error %s, retrying attempt=%d', type(exc).__name__, attempt + 1)
                    except ValueError as exc:
                        if emitted or last:
                            raise
                        log.warning('Model stream unusable: %s attempt=%d chars=%d', type(exc).__name__, attempt + 1, len(content))
                    await asyncio.sleep(_retry_delay(attempt))
        if not isinstance(raw, dict):
            raise ValueError('invalid model response')
        return raw
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            raise ServiceError('模型服务认证失败，请检查 API Key 和模型使用权限。') from exc
        if status == 404:
            raise ServiceError('模型接口或模型不存在，请检查服务地址和模型名称。') from exc
        if status == 429:
            raise ServiceError('模型服务请求受限，请检查配额或稍后重试。', 429) from exc
        raise ServiceError('模型服务请求失败，请检查地址、模型能力或稍后重试。') from exc
    except httpx.HTTPError as exc:
        raise ServiceError('无法连接模型服务或请求超时，请检查网络后重试。') from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning('Invalid model response: %s: %s', type(exc).__name__, exc)
        raise ModelOutputError('模型返回内容不完整或格式无效，请重试。') from exc
    finally:
        # 只释放自己拿到的令牌：排队超时/被取消时释放会凭空放大并发上限。
        if acquired:
            SEMAPHORE.release()

