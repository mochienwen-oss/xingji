import { useEffect } from 'react';

/**
 * 软键盘遮挡高度：iOS 上 innerHeight 不变、visualViewport 变小并整体上移，
 * 两段都要算进去。没有 visualViewport 的环境（旧浏览器、jsdom）按 0 处理。
 */
export function readKeyboardInset(): number {
  const viewport = typeof window === 'undefined' ? null : window.visualViewport;
  if (!viewport) return 0;
  return Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
}

/**
 * 把键盘遮挡高度写进 documentElement 的 --kb-inset（px）。
 * 布局里用 calc(100dvh - var(--kb-inset)) 表达「键盘上方」，不再依赖视口高度单位的手写偏移。
 */
export function useVisualViewport(): void {
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const viewport = window.visualViewport;
    const root = document.documentElement;
    let frame = 0;

    const write = () => {
      frame = 0;
      root.style.setProperty('--kb-inset', `${Math.round(readKeyboardInset())}px`);
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(write);
    };

    // 先同步写一次，避免首帧按旧值布局；后续 resize/scroll 用 rAF 合并。
    write();
    window.addEventListener('resize', schedule);
    window.addEventListener('orientationchange', schedule);
    viewport?.addEventListener('resize', schedule);
    viewport?.addEventListener('scroll', schedule);
    return () => {
      if (frame !== 0) cancelAnimationFrame(frame);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('orientationchange', schedule);
      viewport?.removeEventListener('resize', schedule);
      viewport?.removeEventListener('scroll', schedule);
      root.style.removeProperty('--kb-inset');
    };
  }, []);
}