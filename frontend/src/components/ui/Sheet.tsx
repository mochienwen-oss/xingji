import { useEffect, useRef, type ReactNode } from 'react';
import { usePageActive } from '../../app/providers/PageActiveProvider';
import { useBodyScrollLock } from '../../lib/useBodyScrollLock';
import { useSheetDrag, type SheetDetent } from '../../lib/useSheetDrag';
import { CloseIcon } from '../icons';
import { IconButton } from './IconButton';
import { cx } from './cx';
import styles from './Sheet.module.css';

export type SheetProps = {
  open: boolean;
  /** peek 112px / half 46dvh / full 屏幕高减 56px 顶栏。 */
  detent: SheetDetent;
  onDetentChange: (detent: SheetDetent) => void;
  /** 传了才允许关闭：遮罩、倒数第二档下拉、Escape、关闭按钮。 */
  onClose?: () => void;
  /** 标题元素的 id，本组件只负责 aria-labelledby。 */
  labelledBy: string;
  /** 固定在抽屉底部、不随内容滚动的操作栏。 */
  footer?: ReactNode;
  /** 追加在抽屉本体上的类名，供页面在桌面等断点覆盖几何。 */
  className?: string;
  children: ReactNode;
};

/**
 * 移动端底部抽屉：常驻挂载，靠 open 切换 transform，
 * 高度由 data-detent 交给 CSS，拖拽只负责换算档位。
 */
export function Sheet({ open, detent, onDetentChange, onClose, labelledBy, footer, className, children }: SheetProps) {
  const sheetRef = useRef<HTMLElement | null>(null);
  const pageActive = usePageActive();
  const { dragging, style, handleProps } = useSheetDrag({ detent, onDetentChange, onClose, sheetRef });

  // 抽屉打开时锁页面滚动，关闭后恢复；页面被路由收起时也要释放。
  useBodyScrollLock(open && pageActive);

  useEffect(() => {
    if (!open || !pageActive || !onClose) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, pageActive, onClose]);

  return (
    <div className={cx(styles.layer, onClose && styles.modal, !open && styles.closed)} inert={!open}>
      {onClose ? (
        <button
          type="button"
          className={styles.backdrop}
          tabIndex={-1}
          aria-label="关闭面板"
          onClick={() => {
            if (!dragging) onClose();
          }}
        />
      ) : null}
      <section
        ref={sheetRef}
        className={cx(styles.sheet, className)}
        style={style}
        data-detent={detent}
        role="dialog"
        aria-modal={onClose ? true : undefined}
        aria-labelledby={labelledBy}
        aria-hidden={!open}
      >
        <div className={styles.handleRow}>
          <button
            type="button"
            className={styles.grabber}
            aria-label="调整面板高度"
            aria-expanded={detent === 'full'}
            {...handleProps}
          >
            <span className={styles.bar} aria-hidden="true" />
          </button>
          {onClose ? (
            <IconButton className={styles.close} label="关闭" onClick={onClose}>
              <CloseIcon />
            </IconButton>
          ) : null}
        </div>
        <div className={cx(styles.content, Boolean(footer) && styles.withFooter, dragging && styles.locked)}>
          {children}
        </div>
        {footer ? <div className={styles.footer}>{footer}</div> : null}
      </section>
    </div>
  );
}