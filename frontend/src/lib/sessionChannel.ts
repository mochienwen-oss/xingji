/** 跨标签页会话同步：同一浏览器的标签页共享 cookie，任一标签登录/注册/退出后，
 * 广播通知其他标签重新拉取 /api/me，避免界面停留在上一个账号的数据上。 */
export type SessionChange = { username: string | null };

type SessionChangeListener = (change: SessionChange) => void;

const CHANNEL_NAME = 'xingji-session';
const STORAGE_KEY = 'xingji:session-ping';

// 惰性单例：首次用到时才建通道；环境不支持或构造失败时记为 null，走 localStorage 兜底。
let channel: BroadcastChannel | null | undefined;
const channelListeners = new Set<SessionChangeListener>();

function resolveChannel(): BroadcastChannel | null {
  if (channel !== undefined) return channel;
  channel = null;
  try {
    if (typeof BroadcastChannel !== 'undefined') {
      channel = new BroadcastChannel(CHANNEL_NAME);
    }
  } catch {
    // 隐私模式等极端环境下构造可能失败：保持 null，用 storage 事件兜底。
    channel = null;
  }
  return channel;
}

/** 只接受 { username: string | null } 形状的数据；坏消息返回 undefined（忽略，不当成退出）。 */
function readUsername(data: unknown): string | null | undefined {
  if (!data || typeof data !== 'object' || !('username' in data)) return undefined;
  const username = (data as { username: unknown }).username;
  if (username === null || typeof username === 'string') return username;
  return undefined;
}

/** 登录/注册/退出后调用。通知只是尽力而为：任何异常都吞掉，不能影响登录流程。 */
export function broadcastSessionChange(username: string | null): void {
  try {
    const target = resolveChannel();
    if (target) {
      target.postMessage({ username });
      return;
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ username, at: Date.now() }));
  } catch {
    // 同步通知失败时，其他标签最多晚一次手动刷新才对齐。
  }
}

/** 订阅其他标签的会话变更，返回退订函数；多次订阅互不影响。 */
export function onSessionChange(listener: SessionChangeListener): () => void {
  if (typeof window === 'undefined') return () => {};
  try {
    const target = resolveChannel();
    if (target) {
      channelListeners.add(listener);
      if (!target.onmessage) {
        target.onmessage = (event: MessageEvent) => {
          const username = readUsername(event.data);
          if (username === undefined) return;
          for (const item of [...channelListeners]) {
            try {
              item({ username });
            } catch {
              // 单个订阅者出错不影响其他订阅者。
            }
          }
        };
      }
      return () => {
        channelListeners.delete(listener);
      };
    }
  } catch {
    // 落到下面的 storage 兜底。
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    let username: string | null | undefined;
    try {
      username = readUsername(event.newValue ? JSON.parse(event.newValue) : null);
    } catch {
      return;
    }
    if (username === undefined) return;
    listener({ username });
  };
  window.addEventListener('storage', onStorage);
  return () => window.removeEventListener('storage', onStorage);
}
