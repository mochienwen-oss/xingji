import { Button } from '../ui/Button';
import styles from './TripWorkspace.module.css';

type Props = {
  dirty: boolean;
  busy: boolean;
  onSave: () => void;
  onDiscard: () => void;
};

/** 只在有未保存修改时从底部滑入的 56px 保存条。 */
export function SaveBar({ dirty, busy, onSave, onDiscard }: Props) {
  if (!dirty) return null;
  return (
    <div className={styles.saveBar} role="region" aria-label="未保存的修改" aria-live="polite">
      <p className={styles.saveText}>有未保存的修改</p>
      <div className={styles.saveActions}>
        <Button variant="text" onClick={onDiscard} disabled={busy}>
          放弃
        </Button>
        <Button onClick={onSave} loading={busy}>
          保存
        </Button>
      </div>
    </div>
  );
}
