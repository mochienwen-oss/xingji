import { useEffect, useRef, type RefObject } from 'react';
import { useBodyScrollLock } from './useBodyScrollLock';

type Options = {
  /** 是否启用；false 时不改 DOM，也不抢焦点。 */
  active?: boolean;
  /** Escape 与关闭按钮的统一出口（内部用 ref 取最新回调，不会重挂副作用）。 */
  onClose?: () => void;
  /** Escape 是否触发 onClose，默认 true。 */
  escape?: boolean;
  /** 打开时的首个焦点，缺省为容器内第一个可聚焦元素。 */
  initialFocus?: RefObject<HTMLElement | null>;
};

const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'TEMPLATE', 'NOSCRIPT']);
const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

/** 只收可操作的元素：disabled、aria-hidden、[inert] 与零尺寸节点一律排除。 */
function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(item =>
    !item.hasAttribute('disabled') &&
    item.getAttribute('aria-hidden') !== 'true' &&
    !item.closest('[inert]') &&
    (item.offsetWidth > 0 || item.offsetHeight > 0 || item.getClientRects().length > 0)
  );
}

/**
 * 模态浮层的焦点与滚动管理：首焦点、Tab 循环、Escape 关闭、
 * 背景 inert / aria-hidden / pointer-events 封锁、body 滚动锁，
 * 关闭后把焦点还给打开前的元素。
 */
export function useFocusTrap(rootRef: RefObject<HTMLElement | null>, options: Options = {}) {
  const { active = true, onClose, escape = true, initialFocus } = options;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // 和 Sheet 共用引用计数：两个浮层同时关闭时不会互相把 body 锁回去。
  useBodyScrollLock(active);

  useEffect(() => {
    if (!active) return;
    const root = rootRef.current;
    if (!root) return;

    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // 先把焦点移进浮层，再封锁背景：避免 Chrome 对「aria-hidden 子树仍持有焦点」告警。
    const target = initialFocus?.current ?? focusables(root)[0] ?? root;
    target.focus({ preventScroll: true });
    const hidden: { el: HTMLElement; inert: boolean; aria: string | null; pointer: string }[] = [];
    for (const node of Array.from(document.body.children)) {
      if (!(node instanceof HTMLElement) || SKIP_TAGS.has(node.tagName)) continue;
      if (node === root || node.contains(root)) continue;
      hidden.push({ el: node, inert: node.hasAttribute('inert'), aria: node.getAttribute('aria-hidden'), pointer: node.style.pointerEvents });
      node.setAttribute('inert', '');
      node.setAttribute('aria-hidden', 'true');
      node.style.pointerEvents = 'none';
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && escape) {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current?.();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables(root);
      if (!items.length) {
        event.preventDefault();
        root.focus({ preventScroll: true });
        return;
      }
      const first = items[0], last = items[items.length - 1];
      const current = document.activeElement;
      if (!current || !root.contains(current)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && current === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);

    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      for (const item of hidden) {
        if (!item.inert) item.el.removeAttribute('inert');
        if (item.aria === null) item.el.removeAttribute('aria-hidden');
        else item.el.setAttribute('aria-hidden', item.aria);
        item.el.style.pointerEvents = item.pointer;
      }
      if (previous && previous !== root && previous !== document.body && previous.isConnected) previous.focus({ preventScroll: true });
    };
  }, [active, escape, rootRef, initialFocus]);
}
