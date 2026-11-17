import { useId, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { usePageActive } from '../../app/providers/PageActiveProvider';
import { useFocusTrap } from '../../lib/useFocusTrap';
import { CloseIcon } from '../icons';
import { IconButton } from './IconButton';
import { cx } from './cx';
import styles from './Dialog.module.css';

export type DialogProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  /** 打开时要聚焦的元素；缺省聚焦面板里第一个可操作元素。 */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** 提交中：关闭按钮、遮罩、Escape 全部失效。 */
  busy?: boolean;
  className?: string;
};

/**
 * 模态对话框：手机上是底部抽屉，桌面 480px 居中。
 * 焦点陷阱、背景 inert、body 滚动锁都由 useFocusTrap 负责，
 * 这里不再叠加 useBodyScrollLock，避免两套保存/还原互相覆盖。
 */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  initialFocusRef,
  busy = false,
  className,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const pageActive = usePageActive();

  useFocusTrap(panelRef, {
    active: open && pageActive,
    escape: !busy,
    onClose,
    initialFocus: initialFocusRef,
  });

  const close = () => {
    if (!busy) onClose();
  };

  // 常驻页面被路由收起时，portal 不能继续浮在其他页面上。
  if (!open || !pageActive) return null;

  return createPortal(
    <div className={styles.layer}>
      <div className={styles.backdrop} aria-hidden="true" onClick={close} />
      <div
        ref={panelRef}
        className={cx(styles.panel, className)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <div className={styles.body}>{children}</div>
        {footer ? <div className={styles.footer}>{footer}</div> : null}
        <IconButton className={styles.close} label="关闭" onClick={close} disabled={busy}>
          <CloseIcon />
        </IconButton>
      </div>
    </div>,
    document.body,
  );
}
