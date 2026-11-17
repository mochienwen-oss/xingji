import { useEffect, useMemo, useRef, useState } from 'react';

/** 实时协同的在线成员条目（与 /live WebSocket 的 presence 字段一致）。 */
export type LivePresence = { user_id: number; username: string };

/** 连接状态：connecting 建连中 / open 已连接 / closed 已断开（含未启用）。 */
export type LiveStatus = 'connecting' | 'open' | 'closed';

/** 远端保存回执：version 是服务器新版本，by 为 null 表示系统或匿名改动。 */
export type LiveTripUpdate = { version: number; by: LivePresence | null };

type UseTripLiveOptions = { tripId: number | null; enabled: boolean };

type UseTripLiveResult = {
  status: LiveStatus;
  presence: LivePresence[];
  onlineCount: number;
  lastVersion: number | null;
  lastUpdate: LiveTripUpdate | null;
};

/** 断线重连退避：1s 起步逐级翻倍，30s 封顶；收到 hello 后重新从头计数。 */
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 15000, 30000];

/** 心跳周期：连接打开后每 20s 发一次 ping。 */
const HEARTBEAT_INTERVAL_MS = 20_000;

/** 空闲判死：45s 没收到任何消息就主动断开，走重连流程。 */
const IDLE_TIMEOUT_MS = 45_000;

/**
 * 服务端鉴权性关闭码：4401 会话失效 / 4403 非成员 / 4404 行程不存在。
 * 重连只会被立刻再踢一次，直接停在 closed，等页面轮询去处理访问状态。
 */
const FATAL_CLOSE_CODES = [4401, 4403, 4404];

function isPresence(value: unknown): value is LivePresence {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as LivePresence).user_id === 'number' &&
    typeof (value as LivePresence).username === 'string'
  );
}

function toPresenceList(value: unknown): LivePresence[] {
  return Array.isArray(value) ? value.filter(isPresence) : [];
}

function liveUrl(tripId: number): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}/api/trips/${tripId}/live`;
}

/**
 * 行程实时协同连接：presence 提供在线成员名单，trip_updated 同步远端版本。
 * 断线按退避重连；卸载或行程切换时彻底清理，不会在卸载后更新组件状态。
 */
export function useTripLive({ tripId, enabled }: UseTripLiveOptions): UseTripLiveResult {
  const [status, setStatus] = useState<LiveStatus>('closed');
  const [presence, setPresence] = useState<LivePresence[]>([]);
  const [lastVersion, setLastVersion] = useState<number | null>(null);
  const [lastUpdate, setLastUpdate] = useState<LiveTripUpdate | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const idleTimerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  // 卸载/重建后的迟到回调防线：false 时所有 handler 直接哑火。
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    // 无行程、被禁用或环境不支持 WebSocket 时保持 closed，不建连也不抛错。
    if (!enabled || tripId == null || typeof WebSocket === 'undefined') {
      setStatus('closed');
      setPresence([]);
      return;
    }

    // 收窄后的 id 单独存放：嵌套函数里不会再被 TS 收回 number | null。
    const id = tripId;

    const clearTimer = (ref: { current: number | null }) => {
      if (ref.current !== null) {
        window.clearTimeout(ref.current);
        ref.current = null;
      }
    };

    const settle = (next: LiveStatus) => {
      if (aliveRef.current) setStatus(next);
    };

    // 45s 没有任何消息（连 pong 都没有）就认为连接假死，主动断开触发重连。
    function armIdle() {
      clearTimer(idleTimerRef);
      idleTimerRef.current = window.setTimeout(() => {
        try {
          socketRef.current?.close();
        } catch {
          /* 已在关闭中 */
        }
      }, IDLE_TIMEOUT_MS);
    }

    function scheduleReconnect() {
      if (!aliveRef.current) return;
      const delay = RECONNECT_DELAYS_MS[Math.min(attemptRef.current, RECONNECT_DELAYS_MS.length - 1)];
      attemptRef.current += 1;
      clearTimer(reconnectTimerRef);
      reconnectTimerRef.current = window.setTimeout(connect, delay);
    }

    function connect() {
      settle('connecting');
      let socket: WebSocket;
      try {
        socket = new WebSocket(liveUrl(id));
      } catch {
        // 非法 URL 等构造异常按断线处理，交给退避重连。
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        if (socketRef.current !== socket) return;
        settle('open');
        armIdle();
        clearTimer(heartbeatTimerRef);
        heartbeatTimerRef.current = window.setInterval(() => {
          const current = socketRef.current;
          if (current !== socket || current.readyState !== WebSocket.OPEN) return;
          try {
            current.send(JSON.stringify({ type: 'ping' }));
          } catch {
            /* 发送失败交给 onclose 兜底 */
          }
        }, HEARTBEAT_INTERVAL_MS);
      };

      socket.onmessage = (event: MessageEvent) => {
        if (socketRef.current !== socket) return;
        armIdle();
        let data: unknown;
        try {
          data = JSON.parse(typeof event.data === 'string' ? event.data : '');
        } catch {
          return; // 非 JSON 消息只用于保活，不更新状态。
        }
        if (typeof data !== 'object' || data === null) return;
        if (!aliveRef.current) return;
        const message = data as Record<string, unknown>;
        if (message.type === 'hello') {
          attemptRef.current = 0;
          setPresence(toPresenceList(message.presence));
          if (typeof message.version === 'number') setLastVersion(message.version);
        } else if (message.type === 'presence') {
          setPresence(toPresenceList(message.presence));
        } else if (message.type === 'trip_updated') {
          if (typeof message.version !== 'number') return;
          const by = isPresence(message.by) ? message.by : null;
          setLastVersion(message.version);
          setLastUpdate({ version: message.version, by });
        }
        // pong 与未知类型：仅参与保活，不触碰状态。
      };

      socket.onclose = (event?: CloseEvent) => {
        if (socketRef.current !== socket) return;
        socketRef.current = null;
        clearTimer(heartbeatTimerRef);
        clearTimer(idleTimerRef);
        settle('closed');
        if (aliveRef.current) setPresence([]);
        // 服务端已经判定会话/成员无效：不再退避重连，避免频繁重连和被反复踢的噪音。
        if (event && FATAL_CLOSE_CODES.includes(event.code)) return;
        scheduleReconnect();
      };

      socket.onerror = () => {
        if (socketRef.current !== socket) return;
        try {
          socket.close();
        } catch {
          /* 已在关闭中 */
        }
      };
    }

    connect();

    return () => {
      aliveRef.current = false;
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        // 置空 handler：close 可能异步回调，卸载后不能再 setState 或重连。
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        try {
          socket.close();
        } catch {
          /* 已在关闭中 */
        }
      }
      clearTimer(reconnectTimerRef);
      clearTimer(heartbeatTimerRef);
      clearTimer(idleTimerRef);
      attemptRef.current = 0;
    };
  }, [tripId, enabled]);

  return useMemo(
    () => ({
      status,
      presence,
      onlineCount: presence.length,
      lastVersion,
      lastUpdate,
    }),
    [status, presence, lastVersion, lastUpdate]
  );
}
