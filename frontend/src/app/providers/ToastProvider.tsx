import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { ToastViewport, type ToastItem, type ToastTone } from '../../components/ui/Toast';

/** 单条提示在屏时间（ms）。 */
export const TOAST_DURATION = 3000;
/** 同时最多几条：超出的挤掉最早的一条。 */
export const TOAST_LIMIT = 3;

export type ConfirmOptions = {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** 破坏性动作：确认按钮用 danger，并放在右侧。 */
  danger?: boolean;
};

type PendingConfirm = ConfirmOptions & { resolve: (value: boolean) => void };

type ToastApi = { toast: (message: string, tone?: ToastTone) => void };
type ConfirmApi = (options: ConfirmOptions) => Promise<boolean>;

const ToastContext = createContext<ToastApi | null>(null);
const ConfirmContext = createContext<ConfirmApi | null>(null);

let nextToastId = 1;

/**
 * 提示与服务端确认：toast 队列最多 3 条、3 秒自动消失；
 * confirm 用队列串起来，同一时间只弹一个确认框。
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [queue, setQueue] = useState<PendingConfirm[]>([]);
  const queueRef = useRef(queue);
  queueRef.current = queue;
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setToasts(current => current.filter(item => item.id !== id));
  }, []);

  const toast = useCallback((message: string, tone: ToastTone = 'info') => {
    const id = nextToastId;
    nextToastId += 1;
    // 同一句提示连发时只保留最新一条，避免相同内容在屏幕上叠成一片。
    setToasts(current => [
      ...current.filter(item => item.message !== message || item.tone !== tone),
      { id, message, tone },
    ].slice(-TOAST_LIMIT));
  }, []);

  const confirm = useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>(resolve => {
        setQueue(current => [...current, { ...options, resolve }]);
      }),
    [],
  );

  const settle = useCallback((value: boolean) => {
    const [head, ...rest] = queueRef.current;
    if (!head) return;
    queueRef.current = rest;
    setQueue(rest);
    head.resolve(value);
  }, []);

  // 只给新出现的提示挂计时器；被挤掉或手动关闭的同时清掉。
  useEffect(() => {
    const timerMap = timers.current;
    for (const item of toasts) {
      if (timerMap.has(item.id)) continue;
      timerMap.set(item.id, window.setTimeout(() => dismiss(item.id), TOAST_DURATION));
    }
    for (const [id, timer] of timerMap) {
      if (!toasts.some(item => item.id === id)) {
        window.clearTimeout(timer);
        timerMap.delete(id);
      }
    }
  }, [toasts, dismiss]);

  useEffect(() => {
    const timerMap = timers.current;
    return () => {
      for (const timer of timerMap.values()) window.clearTimeout(timer);
      timerMap.clear();
    };
  }, []);

  const toastApi = useMemo(() => ({ toast }), [toast]);
  const pending = queue[0] ?? null;

  return (
    <ToastContext.Provider value={toastApi}>
      <ConfirmContext.Provider value={confirm}>
        {children}
        {createPortal(<ToastViewport toasts={toasts} onDismiss={dismiss} />, document.body)}
        {pending ? (
          <ConfirmDialog
            open
            title={pending.title}
            body={pending.body}
            confirmLabel={pending.confirmLabel}
            cancelLabel={pending.cancelLabel}
            danger={pending.danger}
            onConfirm={() => settle(true)}
            onCancel={() => settle(false)}
          />
        ) : null}
      </ConfirmContext.Provider>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast 必须在 ToastProvider 内使用');
  return context;
}

export function useConfirm(): ConfirmApi {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error('useConfirm 必须在 ToastProvider 内使用');
  return context;
}
