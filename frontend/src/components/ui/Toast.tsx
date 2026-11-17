import { CloseIcon } from '../icons';
import { IconButton } from './IconButton';
import { cx } from './cx';
import styles from './Toast.module.css';

export type ToastTone = 'info' | 'success' | 'error';

export type ToastItem = {
  id: number;
  message: string;
  tone: ToastTone;
};

export type ToastProps = ToastItem & {
  onDismiss?: (id: number) => void;
};

/** 单条提示：ink 底、纸白字，可手动关闭；错误用 alert 立即播报。 */
export function Toast({ id, message, tone, onDismiss }: ToastProps) {
  return (
    <div className={cx(styles.toast, styles[tone])} role={tone === 'error' ? 'alert' : undefined}>
      <span className={styles.message}>{message}</span>
      {onDismiss ? (
        <IconButton className={styles.close} label="关闭提示" onClick={() => onDismiss(id)}>
          <CloseIcon />
        </IconButton>
      ) : null}
    </div>
  );
}

export type ToastViewportProps = {
  toasts: readonly ToastItem[];
  onDismiss: (id: number) => void;
};

/**
 * 固定视口：底部导航上方，aria-live polite。
 * 没有提示时也保持挂载，读屏器才听得到后续插入的内容。
 */
export function ToastViewport({ toasts, onDismiss }: ToastViewportProps) {
  return (
    <div
      className={styles.viewport}
      role="region"
      aria-label="通知"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map(item => (
        <Toast key={item.id} id={item.id} message={item.message} tone={item.tone} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
