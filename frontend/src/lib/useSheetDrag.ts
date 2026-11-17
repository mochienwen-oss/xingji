import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react';

export type SheetDetent = 'peek' | 'half' | 'full';

/** 由矮到高的三档顺序，吸附逻辑全部基于这个顺序。 */
export const SHEET_DETENTS: readonly SheetDetent[] = ['peek', 'half', 'full'];

/** 松手速度阈值（px/s）：超过就按方向跨一档，否则看位移。 */
export const SNAP_VELOCITY = 500;

/** 上拉最多给出的位移，避免把固定高度的抽屉拖出底部空隙。 */
const PULL_UP_LIMIT = 48;

/** 下拖超过当前高度的这个比例退一档；至少 48px。 */
const DRAG_RATIO = 0.25;
const DRAG_STEP = 48;

/** 速度只回看松手前这段时间（ms）：长按后松手不该被历史抖动带飞。 */
const VELOCITY_WINDOW = 100;

type DragSample = { y: number; at: number };

/** 纯函数：按松手速度决定停在哪个档位。负速度是往上拖。 */
export function nextDetent(current: SheetDetent, velocity: number): SheetDetent {
  const index = SHEET_DETENTS.indexOf(current);
  if (velocity <= -SNAP_VELOCITY) return SHEET_DETENTS[Math.min(SHEET_DETENTS.length - 1, index + 1)];
  if (velocity >= SNAP_VELOCITY) return SHEET_DETENTS[Math.max(0, index - 1)];
  return current;
}

/** 纯函数：速度不够时按挡位位移判断；上和下用不同的阈值。 */
export function detentAfterDrag(current: SheetDetent, offset: number, height: number): SheetDetent {
  const index = SHEET_DETENTS.indexOf(current);
  if (offset >= Math.max(DRAG_STEP, height * DRAG_RATIO)) return SHEET_DETENTS[Math.max(0, index - 1)];
  if (offset <= -DRAG_STEP) return SHEET_DETENTS[Math.min(SHEET_DETENTS.length - 1, index + 1)];
  return current;
}

/** 只有 peek 能直接关闭：半屏/全屏先退档，避免误关。 */
export function shouldDismiss(current: SheetDetent, offset: number, velocity: number, height: number): boolean {
  if (current !== 'peek') return false;
  return offset >= Math.max(DRAG_STEP, height * DRAG_RATIO) || velocity >= SNAP_VELOCITY;
}

/** 纯函数：从 rAF 采样点算松手速度（px/s）；样本太旧或不足时返回 0。 */
export function releaseVelocity(samples: readonly DragSample[], now: number): number {
  if (samples.length < 2) return 0;
  const last = samples[samples.length - 1];
  if (now - last.at > VELOCITY_WINDOW) return 0;
  let first = samples[samples.length - 2];
  for (let index = samples.length - 2; index >= 0; index -= 1) {
    if (last.at - samples[index].at > VELOCITY_WINDOW) break;
    first = samples[index];
  }
  const span = last.at - first.at;
  if (span <= 0) return 0;
  return ((last.y - first.y) / span) * 1000;
}

type DragSession = {
  pointerId: number;
  startY: number;
  lastY: number;
  samples: DragSample[];
  frame: number;
  moved: boolean;
};

export type UseSheetDragOptions = {
  detent: SheetDetent;
  onDetentChange: (next: SheetDetent) => void;
  onClose?: () => void;
  /** 抽屉主体，用于量当前高度；缺省按视口的 46% 估算。 */
  sheetRef?: RefObject<HTMLElement | null>;
};

export type UseSheetDragResult = {
  dragging: boolean;
  offset: number;
  /** 拖拽中的位移，交给抽屉根节点的 style。 */
  style: CSSProperties;
  /** 把手（按钮）需要的指针与键盘事件。 */
  handleProps: {
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerMove: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerUp: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerCancel: (event: ReactPointerEvent<HTMLElement>) => void;
    onClick: () => void;
    onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  };
};

/**
 * 抽屉把手的拖拽：pointerdown/move/up + rAF 采样速度，松手按速度/位移吸附三档。
 * 只做「把手 → 档位」的换算，高度与动画由 Sheet 的 CSS 负责。
 */
export function useSheetDrag({ detent, onDetentChange, onClose, sheetRef }: UseSheetDragOptions): UseSheetDragResult {
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const session = useRef<DragSession | null>(null);
  const suppressClick = useRef(false);

  const measure = useCallback(() => {
    const node = sheetRef?.current;
    if (node && node.offsetHeight > 0) return node.offsetHeight;
    return typeof window === 'undefined' ? 0 : window.innerHeight * 0.46;
  }, [sheetRef]);

  useEffect(
    () => () => {
      const current = session.current;
      if (current && current.frame !== 0) cancelAnimationFrame(current.frame);
    },
    [],
  );

  function onPointerDown(event: ReactPointerEvent<HTMLElement>) {
    if (session.current || !event.isPrimary || event.button !== 0) return;
    const at = performance.now();
    session.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      lastY: event.clientY,
      samples: [{ y: event.clientY, at }],
      frame: 0,
      moved: false,
    };
    suppressClick.current = false;
    setOffset(0);
    setDragging(true);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // setPointerCapture 在部分环境（含 jsdom）不可用，拖拽仍按事件冒泡工作。
    }
  }

  function onPointerMove(event: ReactPointerEvent<HTMLElement>) {
    const current = session.current;
    if (!current || current.pointerId !== event.pointerId) return;
    current.lastY = event.clientY;
    const delta = event.clientY - current.startY;
    if (Math.abs(delta) > 4) current.moved = true;
    setOffset(delta > 0 ? delta : Math.max(delta, -PULL_UP_LIMIT));
    if (current.frame === 0) {
      current.frame = requestAnimationFrame(() => {
        current.frame = 0;
        current.samples.push({ y: current.lastY, at: performance.now() });
        if (current.samples.length > 8) current.samples.shift();
      });
    }
  }

  function finish(event: ReactPointerEvent<HTMLElement>, cancelled: boolean) {
    const current = session.current;
    if (!current || current.pointerId !== event.pointerId) return;
    session.current = null;
    if (current.frame !== 0) cancelAnimationFrame(current.frame);
    setDragging(false);
    setOffset(0);
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // 与 setPointerCapture 同理：没有捕获时无需释放。
    }
    if (cancelled) return;

    const height = measure();
    const delta = event.clientY - current.startY;
    if (current.moved) current.samples.push({ y: event.clientY, at: performance.now() });
    const velocity = releaseVelocity(current.samples, performance.now());
    suppressClick.current = current.moved;

    if (onClose && shouldDismiss(detent, delta, velocity, height)) {
      onClose();
      return;
    }
    const target =
      Math.abs(velocity) >= SNAP_VELOCITY ? nextDetent(detent, velocity) : detentAfterDrag(detent, delta, height);
    if (target !== detent) onDetentChange(target);
  }

  function onPointerUp(event: ReactPointerEvent<HTMLElement>) {
    finish(event, false);
  }

  function onPointerCancel(event: ReactPointerEvent<HTMLElement>) {
    finish(event, true);
  }

  function onClick() {
    // 拖拽松手后浏览器还会补一个 click，这里吞掉，避免拖完又跳一档。
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    const index = SHEET_DETENTS.indexOf(detent);
    const next = SHEET_DETENTS[Math.min(index + 1, SHEET_DETENTS.length - 1)];
    if (next !== detent) onDetentChange(next);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    const index = SHEET_DETENTS.indexOf(detent);
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      const next = SHEET_DETENTS[Math.min(index + 1, SHEET_DETENTS.length - 1)];
      if (next !== detent) onDetentChange(next);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (index === 0) {
        onClose?.();
        return;
      }
      onDetentChange(SHEET_DETENTS[index - 1]);
    }
  }

  return {
    dragging,
    offset,
    style: offset === 0 ? {} : { transform: `translateY(${offset}px)` },
    handleProps: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onClick, onKeyDown },
  };
}
