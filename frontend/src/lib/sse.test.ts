import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamSse, type SseError } from './sse';

/** 用可控 reader 模拟 fetch 响应，避免依赖 jsdom 的 ReadableStream/Response 实现。 */
function fakeResponse(chunks: string[], init: {ok?: boolean; status?: number; detail?: string} = {}) {
  let index = 0;
  const ok = init.ok ?? true;
  return {
    ok,
    status: init.status ?? (ok ? 200 : 503),
    json: async () => (init.detail ? {detail: init.detail} : null),
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length
            ? {done: false as const, value: new TextEncoder().encode(chunks[index++])}
            : {done: true as const, value: undefined},
      }),
    },
  } as unknown as Response;
}

function run(chunks: string[], init?: {ok?: boolean; status?: number; detail?: string}) {
  const events: unknown[] = [];
  const errors: SseError[] = [];
  let ended = false;
  let resolve!: () => void;
  const finished = new Promise<void>((done) => { resolve = done; });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse(chunks, init)));
  streamSse({
    url: '/api/planning/chat/stream',
    body: {message: '杭州两天'},
    onEvent: (event) => events.push(event),
    onError: (error) => { errors.push(error); resolve(); },
    onEnd: () => { ended = true; resolve(); },
  });
  return {events, errors, finished, hasEnded: () => ended};
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamSse', () => {
  it('把跨 chunk 被切成两半的 data: 帧拼回一条事件', async () => {
    const result = run(['data: {"type":"pl', 'an"}\n\n']);
    await result.finished;
    expect(result.events).toEqual([{type: 'plan'}]);
    expect(result.hasEnded()).toBe(true);
  });

  it('连接结束时最后一条没有空行收尾的帧也要派发（尾帧回归）', async () => {
    // 回归：服务端写完最后一条事件后直接关流时，缓冲区里不会留下空行；
    // 若不补解析尾帧，用户会丢掉流式回复的最后一个事件。
    const result = run(['data: {"index":1}\n\n', 'data: {"index":2}']);
    await result.finished;
    expect(result.events).toEqual([{index: 1}, {index: 2}]);
  });

  it('接受 CRLF 空行并忽略心跳注释与坏 JSON', async () => {
    const result = run([
      ': keep-alive\r\n\r\n',
      'data: {"ok":true}\r\n\r\n',
      'data: not-json\n\n',
    ]);
    await result.finished;
    expect(result.events).toEqual([{ok: true}]);
  });

  it('非 2xx 转成 http 错误并带上 detail', async () => {
    const result = run([], {ok: false, status: 503, detail: '服务暂时不可用，请稍后重试'});
    await result.finished;
    expect(result.errors).toEqual([{kind: 'http', status: 503, detail: '服务暂时不可用，请稍后重试'}]);
    expect(result.hasEnded()).toBe(false);
  });

  it('fetch 抛错转成 network 错误', async () => {
    const cause = new TypeError('Failed to fetch');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(cause));
    const errors: SseError[] = [];
    let resolve!: () => void;
    const finished = new Promise<void>((done) => { resolve = done; });
    streamSse({url: '/api/x', body: {}, onError: (error) => { errors.push(error); resolve(); }});
    await finished;
    expect(errors).toEqual([{kind: 'network', cause}]);
  });
});
