import { Button } from '../ui/Button';
import { LockIcon } from '../icons';
import styles from './TripWorkspace.module.css';

type Props = {
  busy: boolean;
  onRecheck: () => void;
  onBack: () => void;
};

/** 被移出协作者或行程已删除时的全屏终态，不渲染任何可编辑内容。 */
export function AccessLostState({ busy, onRecheck, onBack }: Props) {
  return (
    <main className={styles.accessLost} role="alert">
      <div className={styles.accessLostCard}>
        <span className={styles.accessLostIcon} aria-hidden="true">
          <LockIcon size={30} />
        </span>
        <h1 className={styles.accessLostTitle}>这段行程已不可访问</h1>
        <p className={styles.accessLostText}>它可能已被删除，或你已不再是这段行程的协作者。</p>
        <div className={styles.accessLostActions}>
          <Button onClick={onRecheck} loading={busy}>
            重新检查
          </Button>
          <Button variant="secondary" onClick={onBack}>
            返回我的行程
          </Button>
        </div>
      </div>
    </main>
  );
}
