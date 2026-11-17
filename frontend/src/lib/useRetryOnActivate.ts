import { useEffect, useRef } from 'react';

/**
 * 常驻页面重新可见时再试一次已经失败的加载。
 *
 * AppShell 会把行程页 hidden 收起而不是卸载：回到同一个行程时 `openTrip` 的
 * tripId 依赖没有变化，页面不会重新请求，访问失效的行程会一直停在错误态。
 * 这里在页面重新 active（或 active 期间新出现失败）时补一次重试；
 * 重试后两个条件都不变时不会重复调用，避免请求自旋。
 */
export function useRetryOnActivate(active: boolean, shouldRetry: boolean, retry: () => void): void {
  const retryRef = useRef(retry);
  retryRef.current = retry;

  useEffect(() => {
    if (active && shouldRetry) retryRef.current();
  }, [active, shouldRetry]);
}
