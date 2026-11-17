import type { ReactNode } from 'react';
import { Button } from './Button';
import { Dialog } from './Dialog';
import styles from './Dialog.module.css';

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  /** 破坏性动作：确认按钮用 danger，并固定在右侧。 */
  danger?: boolean;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
};

/**
 * 确认弹层：取消在左、主行动在右；Escape 与遮罩都等同取消（busy 时无效）。
 * 首焦点落在「取消」上，避免误触破坏性操作。
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger = false,
  cancelLabel = '取消',
  onConfirm,
  onCancel,
  busy = false,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      title={title}
      onClose={onCancel}
      busy={busy}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className={styles.prose}>{body}</div>
    </Dialog>
  );
}
