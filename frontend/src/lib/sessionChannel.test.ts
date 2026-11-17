import { beforeEach, describe, expect, it, vi } from 'vitest';

const CHANNEL_NAME = 'xingji-session';
const STORAGE_KEY = 'xingji:session-ping';

type SessionChange = { username: string | null };
type SessionChannelModule = typeof import('./sessionChannel');

/** 模拟 BroadcastChannel：postMessage 只投给「别的」实例，与真实语义一致（自己收不到自己的消息）。 */
class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = [];
  name: string;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(name: string) {
    this.name = name;
    FakeBroadcastChannel.instances.push(this);
  }

  postMessage(data: unknown): void {
    for (const instance of [...FakeBroadcastChannel.instances]) {
      if (instance !== this) instance.onmessage?.({ data });
    }
  }

  close(): void {}
}

/** 构造即抛错：模拟隐私模式等极端环境。 */
class ThrowingBroadcastChannel {
  name: string;
  constructor(name: string) {
    this.name = name;
    throw new Error('此环境禁用 BroadcastChannel');
  }
  close(): void {}
}

/** 模块里有惰性单例：每个用例 resetModules 后重新 import，拿一份干净的模块。 */
async function loadModule(): Promise<SessionChannelModule> {
  vi.resetModules();
  return await import('./sessionChannel');
}

/** 模拟另一个标签页写入后触发的 storage 事件（本页 setItem 不会触发该事件）。 */
function dispatchStorage(key: string, value: string | null): void {
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: value }));
}

function readPing(): { username?: unknown; at?: unknown } {
  return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Record<string, unknown>;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  FakeBroadcastChannel.instances = [];
});

describe('sessionChannel：BroadcastChannel 主通道', () => {
  it('广播发给其他标签，订阅者也能收到其他标签发来的变更', async () => {
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    const mod = await loadModule();

    const seen: SessionChange[] = [];
    const unsubscribe = mod.onSessionChange((change) => seen.push(change));

    const peer = new FakeBroadcastChannel(CHANNEL_NAME);
    const posted: unknown[] = [];
    peer.onmessage = (event) => posted.push(event.data);

    mod.broadcastSessionChange('auditxj02');
    expect(posted).toEqual([{ username: 'auditxj02' }]);

    peer.postMessage({ username: 'auditxj02' });
    expect(seen).toEqual([{ username: 'auditxj02' }]);

    unsubscribe();
  });

  it('username 为 null 表示退出，照常广播和送达', async () => {
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    const mod = await loadModule();
    const seen: SessionChange[] = [];
    const unsubscribe = mod.onSessionChange((change) => seen.push(change));
    const peer = new FakeBroadcastChannel(CHANNEL_NAME);
    const posted: unknown[] = [];
    peer.onmessage = (event) => posted.push(event.data);

    mod.broadcastSessionChange(null);
    expect(posted).toEqual([{ username: null }]);

    peer.postMessage({ username: null });
    expect(seen).toEqual([{ username: null }]);
    unsubscribe();
  });

  it('退订后不再收到消息', async () => {
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    const mod = await loadModule();
    const seen: SessionChange[] = [];
    const unsubscribe = mod.onSessionChange((change) => seen.push(change));
    const peer = new FakeBroadcastChannel(CHANNEL_NAME);

    unsubscribe();
    peer.postMessage({ username: 'alice' });
    expect(seen).toEqual([]);
  });

  it('多个订阅者互不影响，退订一个另一个仍能收到', async () => {
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    const mod = await loadModule();
    const first: SessionChange[] = [];
    const second: SessionChange[] = [];
    const offFirst = mod.onSessionChange((change) => first.push(change));
    const offSecond = mod.onSessionChange((change) => second.push(change));
    const peer = new FakeBroadcastChannel(CHANNEL_NAME);

    offFirst();
    peer.postMessage({ username: 'alice' });
    expect(first).toEqual([]);
    expect(second).toEqual([{ username: 'alice' }]);
    offSecond();
  });

  it('postMessage 抛异常时广播静默失败，不影响调用方', async () => {
    class ExplodingChannel extends FakeBroadcastChannel {
      postMessage(): void {
        throw new Error('post 失败');
      }
    }
    vi.stubGlobal('BroadcastChannel', ExplodingChannel);
    const mod = await loadModule();

    expect(() => mod.broadcastSessionChange('alice')).not.toThrow();
  });

  it('构造通道抛异常时退化为 localStorage 兜底', async () => {
    vi.stubGlobal('BroadcastChannel', ThrowingBroadcastChannel);
    const mod = await loadModule();

    expect(() => mod.broadcastSessionChange('alice')).not.toThrow();
    expect(readPing()).toMatchObject({ username: 'alice' });
  });
});

describe('sessionChannel：localStorage 兜底', () => {
  it('无 BroadcastChannel 时写 ping，storage 事件送达订阅者，退订后不再收到', async () => {
    vi.stubGlobal('BroadcastChannel', undefined);
    const mod = await loadModule();

    const seen: SessionChange[] = [];
    const unsubscribe = mod.onSessionChange((change) => seen.push(change));

    mod.broadcastSessionChange('auditxj02');
    expect(readPing()).toMatchObject({ username: 'auditxj02' });
    expect(readPing().at).toEqual(expect.any(Number));

    dispatchStorage(STORAGE_KEY, JSON.stringify({ username: 'auditxj02', at: Date.now() }));
    expect(seen).toEqual([{ username: 'auditxj02' }]);

    unsubscribe();
    dispatchStorage(STORAGE_KEY, JSON.stringify({ username: 'dave', at: Date.now() }));
    expect(seen).toEqual([{ username: 'auditxj02' }]);
  });

  it('忽略其它键与坏数据的 storage 事件', async () => {
    vi.stubGlobal('BroadcastChannel', undefined);
    const mod = await loadModule();
    const seen: SessionChange[] = [];
    const unsubscribe = mod.onSessionChange((change) => seen.push(change));

    dispatchStorage('other-key', JSON.stringify({ username: 'alice' }));
    dispatchStorage(STORAGE_KEY, '{不是 json');
    dispatchStorage(STORAGE_KEY, JSON.stringify({ username: 42 }));
    expect(seen).toEqual([]);
    unsubscribe();
  });

  it('兜底路径支持多个订阅者，退订互不影响', async () => {
    vi.stubGlobal('BroadcastChannel', undefined);
    const mod = await loadModule();
    const first: SessionChange[] = [];
    const second: SessionChange[] = [];
    const offFirst = mod.onSessionChange((change) => first.push(change));
    const offSecond = mod.onSessionChange((change) => second.push(change));

    offFirst();
    dispatchStorage(STORAGE_KEY, JSON.stringify({ username: 'carol', at: Date.now() }));
    expect(first).toEqual([]);
    expect(second).toEqual([{ username: 'carol' }]);
    offSecond();
  });
});
