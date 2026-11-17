import { ApiError, api } from './api';

type VersionedTrip = { version?: number };

/** 轮询健康状态：Provider 用它驱动底部「已同步/离线」状态点。 */
export type TripPollStatus = 'synced' | 'offline';

/** 失败退避上限：连续 3 次失败后最多每分钟探测一次。 */
const MAX_INTERVAL_MS = 60000;

/**
 * 轮询一个行程的版本号，服务端版本变化时再取完整行程交给调用方。
 *
 * 版本探测走轻量接口，不刷新高德地点详情；只有版本真正变化才请求完整数据。
 * 页面隐藏时跳过本轮；离线时直接等下一轮，避免无意义请求。请求本身带 8 秒超时，
 * 连续失败按 2 的幂退避（上限 60 秒），成功后回到传入的间隔。
 * 调用方拥有 `getVersion`（通常是指向当前渲染行程的 ref），因此比较的始终是
 * 用户正在看的版本，而不是挂载时捕获的旧值。返回的函数可重复调用。
 *
 * `onStatus` 把连通性变化交给 TripEditorProvider；`onUnavailable` 只在确认行程
 * 真的不可访问（404）时触发，Provider 据此进入 accessLost 并卸载编辑控件。
 */
export function pollTripVersion(
  tripId: number,
  getVersion: () => number | undefined,
  onUpdate: (trip: unknown) => void,
  onUnavailable?: (error: unknown) => void,
  intervalMs = 10000,
  onStatus?: (status: TripPollStatus) => void,
): () => void {
  let stopped = false;
  let failures = 0;
  let timer = 0;

  const clear = () => {
    if (timer) {
      window.clearTimeout(timer);
      timer = 0;
    }
  };

  const schedule = (delay: number) => {
    if (stopped) return;
    clear();
    timer = window.setTimeout(tick, delay);
  };

  function tick() {
    timer = 0;
    if (stopped) return;
    if (document.hidden) {
      schedule(intervalMs);
      return;
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      onStatus?.('offline');
      schedule(intervalMs);
      return;
    }
    const current = getVersion();
    if (typeof current !== 'number') {
      schedule(intervalMs);
      return;
    }

    void api<VersionedTrip>(`/trips/${tripId}/version`, { timeoutMs: 8000 })
      .then(async (payload) => {
        failures = 0;
        if (stopped) return;
        onStatus?.('synced');
        if (typeof payload.version === 'number' && payload.version !== current) {
          const full = await api<unknown>(`/trips/${tripId}`, { timeoutMs: 15000 });
          if (!stopped) onUpdate(full);
        }
      })
      .catch(async (error: unknown) => {
        if (stopped) return;
        // 404 可能是行程真的没了，也可能只是当前部署没有 version 接口（旧进程）。
        // 用一次完整 GET 复核：完整接口也 404 才判定失联；完整接口 200 就静默停表，
        // 不在旧部署上每 10 秒重拉全量行程，也不误禁用保存。
        if (error instanceof ApiError && error.status === 404) {
          try {
            await api<unknown>(`/trips/${tripId}`, { timeoutMs: 15000 });
            onStatus?.('synced');
            stopped = true;
            clear();
          } catch (confirmError) {
            if (stopped) return;
            onStatus?.('offline');
            if (confirmError instanceof ApiError && confirmError.status === 404) {
              stopped = true;
              clear();
              onUnavailable?.(confirmError);
              return;
            }
            failures = Math.min(failures + 1, 3);
          }
          return;
        }
        // 其他网络/鉴权失败不打断轮询，退避后再试。
        onStatus?.('offline');
        failures = Math.min(failures + 1, 3);
      })
      .finally(() => {
        if (stopped) return;
        schedule(failures ? Math.min(intervalMs * 2 ** failures, MAX_INTERVAL_MS) : intervalMs);
      });
  }

  schedule(intervalMs);

  return () => {
    stopped = true;
    clear();
  };
}
