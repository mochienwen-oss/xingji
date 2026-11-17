import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTripLive } from './useTripLive';

/** 最小可用的 WebSocket 假实现：手动推进状态机，记录发送内容。 */
class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event?: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event?: unknown) => void) | null = null;
  onerror: ((event?: unknown) => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  // ---- 测试驱动辅助：模拟浏览器事件 ----
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }

  message(data: unknown) {
    this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) });
  }
}

type LiveProps = { id: number | null; on: boolean };

function renderLive(initialProps: LiveProps = { id: 7, on: true }) {
  return renderHook(({ id, on }: LiveProps) => useTripLive({ tripId: id, enabled: on }), { initialProps });
}

describe('useTripLive', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('禁用或无行程时不建连，启用后按同源规则连接', () => {
    const { result: disabled } = renderLive({ id: 7, on: false });
    expect(disabled.current.status).toBe('closed');
    expect(disabled.current.presence).toEqual([]);
    expect(FakeWebSocket.instances).toHaveLength(0);

    const { result: noTrip } = renderLive({ id: null, on: true });
    expect(noTrip.current.status).toBe('closed');
    expect(FakeWebSocket.instances).toHaveLength(0);

    const { result } = renderLive();
    expect(result.current.status).toBe('connecting');
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toBe(`ws://${location.host}/api/trips/7/live`);
  });

  it('环境没有 WebSocket 时保持 closed 且不抛错', () => {
    vi.stubGlobal('WebSocket', undefined);
    const { result } = renderLive();
    expect(result.current.status).toBe('closed');
    expect(result.current.presence).toEqual([]);
    expect(result.current.lastVersion).toBeNull();
  });

  it('status 依次走 connecting→open→closed，hello 解析在线名单与版本', () => {
    const { result } = renderLive();
    const socket = FakeWebSocket.instances[0];
    expect(result.current.status).toBe('connecting');

    act(() => {
      socket.open();
    });
    expect(result.current.status).toBe('open');

    act(() => {
      socket.message({
        type: 'hello',
        trip_id: 7,
        version: 9,
        presence: [{ user_id: 1, username: '阿岚' }],
        you: { user_id: 1, username: '阿岚' },
      });
    });
    expect(result.current.presence).toEqual([{ user_id: 1, username: '阿岚' }]);
    expect(result.current.onlineCount).toBe(1);
    expect(result.current.lastVersion).toBe(9);
    expect(result.current.lastUpdate).toBeNull();

    act(() => {
      socket.close();
    });
    expect(result.current.status).toBe('closed');
    expect(result.current.presence).toEqual([]);
  });

  it('presence 消息更新在线名单，trip_updated 记录回执', () => {
    const { result } = renderLive();
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
    });

    act(() => {
      socket.message({
        type: 'presence',
        presence: [
          { user_id: 1, username: '阿岚' },
          { user_id: 2, username: '小舟' },
        ],
      });
    });
    expect(result.current.onlineCount).toBe(2);

    act(() => {
      socket.message({ type: 'trip_updated', version: 10, by: { user_id: 2, username: '小舟' } });
    });
    expect(result.current.lastVersion).toBe(10);
    expect(result.current.lastUpdate).toEqual({ version: 10, by: { user_id: 2, username: '小舟' } });

    act(() => {
      socket.message({ type: 'trip_updated', version: 11, by: null });
    });
    expect(result.current.lastUpdate).toEqual({ version: 11, by: null });
    expect(result.current.lastVersion).toBe(11);
  });

  it('未知消息与非法 JSON 被忽略，不崩也不改状态', () => {
    const { result } = renderLive();
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
    });

    act(() => {
      socket.message('不是 JSON{{{');
      socket.message('123');
      socket.message('null');
      socket.message({ type: 'mystery', payload: 1 });
      socket.message({ type: 'trip_updated', by: { user_id: 3 } });
      socket.message({ type: 'presence', presence: '不是数组' });
    });
    expect(result.current.status).toBe('open');
    expect(result.current.presence).toEqual([]);
    expect(result.current.lastVersion).toBeNull();
    expect(result.current.lastUpdate).toBeNull();
  });

  it('断线后 1s 重连，收到 hello 后退避清零', async () => {
    vi.useFakeTimers();
    const { result } = renderLive();
    const first = FakeWebSocket.instances[0];
    act(() => {
      first.open();
    });

    act(() => {
      first.close();
    });
    expect(result.current.status).toBe('closed');
    expect(FakeWebSocket.instances).toHaveLength(1);

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    const second = FakeWebSocket.instances[1];
    act(() => {
      second.open();
      second.message({ type: 'hello', version: 9, presence: [] });
    });
    act(() => {
      second.close();
    });

    // hello 已把退避清零：再断线仍是 1s，而不是 2s。
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it('服务端鉴权性关闭码（4401/4403/4404）不重连', async () => {
    vi.useFakeTimers();
    for (const code of [4401, 4403, 4404]) {
      FakeWebSocket.instances = [];
      const { result, unmount } = renderLive();
      const socket = FakeWebSocket.instances[0];
      act(() => {
        socket.open();
      });
      act(() => {
        socket.close(code);
      });
      expect(result.current.status).toBe('closed');
      expect(result.current.presence).toEqual([]);
      await act(async () => {
        vi.advanceTimersByTime(60000);
      });
      // 会话已失效/不再是成员：重连只会被立刻再踢一次，必须停在 closed。
      expect(FakeWebSocket.instances).toHaveLength(1);
      unmount();
    }
  });

  it('连续失败按 1/2/4/8/15/30s 退避并封顶', async () => {
    vi.useFakeTimers();
    renderLive();
    act(() => {
      FakeWebSocket.instances[0].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      FakeWebSocket.instances[1].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(3);

    act(() => {
      FakeWebSocket.instances[2].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    expect(FakeWebSocket.instances).toHaveLength(4);

    act(() => {
      FakeWebSocket.instances[3].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(8000);
    });
    expect(FakeWebSocket.instances).toHaveLength(5);

    act(() => {
      FakeWebSocket.instances[4].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(15000);
    });
    expect(FakeWebSocket.instances).toHaveLength(6);

    act(() => {
      FakeWebSocket.instances[5].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    expect(FakeWebSocket.instances).toHaveLength(7);

    act(() => {
      FakeWebSocket.instances[6].close();
    });
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    expect(FakeWebSocket.instances).toHaveLength(8);
  });

  it('切换行程关闭旧连接并重建，禁用后彻底断开', () => {
    const { result, rerender } = renderLive();
    const first = FakeWebSocket.instances[0];
    act(() => {
      first.open();
    });

    rerender({ id: 8, on: true });
    expect(first.readyState).toBe(FakeWebSocket.CLOSED);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toBe(`ws://${location.host}/api/trips/8/live`);
    expect(result.current.status).toBe('connecting');

    rerender({ id: 8, on: false });
    expect(result.current.status).toBe('closed');
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('卸载后关闭连接、清空 handler，不再重连', async () => {
    vi.useFakeTimers();
    const { result, unmount } = renderLive();
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
    });

    unmount();
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    expect(socket.onclose).toBeNull();
    expect(socket.onmessage).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(60000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(result.current.status).toBe('open');
  });

  it('每 20s 心跳 ping，45s 无消息则断开并重连', async () => {
    vi.useFakeTimers();
    const { result } = renderLive();
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
    });

    await act(async () => {
      vi.advanceTimersByTime(20000);
    });
    expect(socket.sent).toContain('{"type":"ping"}');

    await act(async () => {
      vi.advanceTimersByTime(20000);
    });
    expect(socket.sent.filter((data) => data === '{"type":"ping"}')).toHaveLength(2);

    // 一直没有任何消息：45s 判死主动断开，1s 后重连。
    await act(async () => {
      vi.advanceTimersByTime(45000);
    });
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    expect(result.current.status).toBe('connecting');
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
