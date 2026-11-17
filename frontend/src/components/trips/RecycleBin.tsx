import type { DeletedTrip } from '../../types/trip';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import styles from './RecycleBin.module.css';
import { tripName } from './tripMeta';

export const RECOVER_DAYS = 7;
const DAY_MS = 86_400_000;

/**
 * 剩余可恢复天数：基于 deleted_at + 7 天本地计算。
 * 已过期或时间戳无法解析时返回 0（由列表过滤掉）。
 */
export function recoverDaysLeft(deletedAt: string, now: number = Date.now()): number {
  const deleted = Date.parse(deletedAt);
  if (Number.isNaN(deleted)) return 0;
  const left = deleted + RECOVER_DAYS * DAY_MS - now;
  if (left <= 0) return 0;
  return Math.min(RECOVER_DAYS, Math.max(1, Math.ceil(left / DAY_MS)));
}

export type RecycleBinProps = {
  open: boolean;
  items: readonly DeletedTrip[];
  onRestore: (id: number) => void;
  onClose: () => void;
  daysLeft?: (deletedAt: string, now?: number) => number;
};

/** 回收站：只列出还在 7 天窗口内的行程，过期项不显示。 */
export function RecycleBin({ open, items, onRestore, onClose, daysLeft = recoverDaysLeft }: RecycleBinProps) {
  const now = Date.now();
  const alive = items.filter(item => daysLeft(item.deleted_at, now) > 0);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="回收站"
      footer={
        <Button variant="secondary" onClick={onClose}>
          关闭
        </Button>
      }
    >
      <p className={styles.note}>删除的行程会保留 7 天，之后自动清理。</p>
      {alive.length === 0 ? (
        <p className={styles.empty}>回收站是空的。</p>
      ) : (
        <ul className={styles.list}>
          {alive.map(item => (
            <li key={item.id} className={styles.item}>
              <div className={styles.text}>
                <p className={styles.name}>{tripName(item)}</p>
                <p className={styles.meta}>
                  {item.city} · 还有 {daysLeft(item.deleted_at, now)} 天可恢复
                </p>
              </div>
              <Button variant="secondary" className={styles.restore} onClick={() => onRestore(item.id)}>
                恢复
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
