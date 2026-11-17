import { useEffect } from 'react';

/** 多个浮层可能同时要求锁滚动：用引用计数共享同一份保存值，最后一个释放时还原。 */
let locks = 0;
let savedOverflow = '';
let savedPaddingRight = '';

function acquire(): void {
  const body = document.body;
  if (locks === 0) {
    savedOverflow = body.style.overflow;
    savedPaddingRight = body.style.paddingRight;
    body.style.overflow = 'hidden';
    const root = document.documentElement;
    const gap = window.innerWidth - root.clientWidth;
    // jsdom 没有布局（clientWidth 为 0）；真实浏览器里只有出现滚动条时 gap 才 > 0。
    if (gap > 0 && root.clientWidth > 0) {
      const padding = Number.parseFloat(getComputedStyle(body).paddingRight) || 0;
      body.style.paddingRight = `${padding + gap}px`;
    }
  }
  locks += 1;
}

function release(): void {
  if (locks === 0) return;
  locks -= 1;
  if (locks > 0) return;
  const body = document.body;
  // useFocusTrap 关闭时也会写 overflow：只有仍归我们管（还是 hidden）才还原，避免互相抢。
  if (body.style.overflow === 'hidden') body.style.overflow = savedOverflow;
  body.style.paddingRight = savedPaddingRight;
}

/** 打开模态/抽屉时锁住页面滚动并补偿桌面滚动条宽度，关闭后恢复打开前的值。 */
export function useBodyScrollLock(locked: boolean): void {
  useEffect(() => {
    if (!locked) return;
    acquire();
    return release;
  }, [locked]);
}
