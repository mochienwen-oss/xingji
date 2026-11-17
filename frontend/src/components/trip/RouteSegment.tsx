import type { Route } from '../../types/trip';
import { cx } from '../ui/cx';
import { routeText, transportLabel } from './workspace';
import styles from './TripWorkspace.module.css';

type Props = {
  route?: Route;
  fallbackMode: string;
  dirty: boolean;
  busy: boolean;
  onRecompute: () => void;
};

/** 两站之间的路线段；缺路线时给出重新计算入口。 */
export function RouteSegment({ route, fallbackMode, dirty, busy, onRecompute }: Props) {
  const text = routeText(route, fallbackMode);

  return (
    <div className={styles.routeSegment}>
      <div className={styles.routeRail} aria-hidden="true">
        <span className={styles.routeDot} />
        <span className={styles.routeLine} />
      </div>
      <div className={styles.routeBody}>
        <span className={cx(styles.routeText, !route && styles.routePending)} aria-live="polite">
          {busy ? `正在计算${transportLabel(fallbackMode)}路线…` : text || '路线待计算'}
          {route && dirty && !busy ? <span className={styles.routeDirty}>未保存</span> : null}
        </span>
        {!route ? (
          <button
            type="button"
            className={styles.recompute}
            disabled={busy || dirty}
            aria-label={`重新计算${transportLabel(fallbackMode)}路线`}
            onClick={onRecompute}
          >
            {busy ? '计算中…' : dirty ? '保存后可重算' : '重新计算'}
          </button>
        ) : null}
      </div>
    </div>
  );
}
