import { useEffect } from 'react';
import { usePageActive } from '../../app/providers/PageActiveProvider';
import type { TripMapView } from '../../types/trip';
import { useBodyScrollLock } from '../../lib/useBodyScrollLock';
import { MapView } from '../MapView';
import { CloseIcon, FitIcon } from '../icons';
import styles from './TripWorkspace.module.css';

type Props = {
  tripView: TripMapView | null;
  city: string;
  expanded: boolean;
  dayLabel: string;
  onToggle: () => void;
};

/** 200/280px 地图面板；全屏时复用同一张地图，不重新挂载。 */
export function TripMapPanel({ tripView, city, expanded, dayLabel, onToggle }: Props) {
  const pageActive = usePageActive();
  useBodyScrollLock(expanded && pageActive);

  useEffect(() => {
    if (!expanded || !pageActive) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onToggle();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [expanded, pageActive, onToggle]);

  return (
    <section
      className={styles.mapPanel}
      aria-label={expanded ? '全屏行程地图' : '行程地图'}
      data-expanded={expanded || undefined}
    >
      <div className={styles.mapCanvas}>
        {tripView ? (
          <MapView
            days={tripView.days}
            city={city}
            backlog={tripView.backlog}
            showBacklog={tripView.showBacklog}
            focusPlace={tripView.focusPlace}
            tripId={tripView.tripId}
            showCaption={false}
          />
        ) : (
          <div className={styles.mapPlaceholder}>地图准备中…</div>
        )}
      </div>
      <div className={styles.mapTop}>
        <span className={styles.mapLabel}>{expanded ? dayLabel : '今日路线'}</span>
        <button
          type="button"
          className={styles.mapToggle}
          aria-expanded={expanded}
          aria-label={expanded ? '退出全屏地图' : '全屏查看地图'}
          onClick={onToggle}
        >
          {expanded ? <CloseIcon /> : <FitIcon />}
          <span>{expanded ? '退出' : '全屏'}</span>
        </button>
      </div>
    </section>
  );
}