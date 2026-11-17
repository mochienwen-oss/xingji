import type { Place } from '../../types/trip';
import { Button } from '../ui/Button';
import { Skeleton } from '../ui/Skeleton';
import styles from './NearbyGrid.module.css';

export type NearbyGridProps = {
  places: Place[];
  loading: boolean;
  error: string;
  hasCenter: boolean;
  onRetry: () => void;
  onSelect: (place: Place) => void;
};

function distanceText(place: Place): string {
  if (typeof place.distance !== 'number' || !Number.isFinite(place.distance)) return place.city || '附近';
  if (place.distance >= 1000) return `${(place.distance / 1000).toFixed(1)} km`;
  return `${Math.round(place.distance)} m`;
}

export function NearbyGrid({ places, loading, error, hasCenter, onRetry, onSelect }: NearbyGridProps) {
  if (loading) {
    return (
      <div className={styles.grid} aria-label="正在加载附近地点" role="status">
        {[0, 1, 2, 3].map((item) => (
          <Skeleton key={item} className={styles.skeleton} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.error} role="alert">
        <p className={styles.errorText}>附近地点没加载出来</p>
        <p className={styles.errorDetail}>{error}</p>
        <Button variant="secondary" onClick={onRetry}>重试</Button>
      </div>
    );
  }

  if (!places.length) {
    return (
      <p className={styles.empty}>
        {hasCenter
          ? '这一带还没有可用的地点。换个城市，或拖动地图再试。'
          : '还没有定位。选一座城市，地图会显示附近的地点。'}
      </p>
    );
  }

  return (
    <div className={styles.grid}>
      {places.slice(0, 20).map((place) => (
        <button
          key={place.id}
          type="button"
          className={styles.card}
          aria-label={`查看${place.name}`}
          onClick={() => onSelect(place)}
        >
          <span className={styles.name}>{place.name}</span>
          <span className={styles.address}>{place.address || '地址以地图为准'}</span>
          {/* 卡片只留距离：高德原始 opentime 是一整段营业时间，塞进 11px 会撑破卡片。 */}
          <span className={styles.meta}>{distanceText(place)}</span>
        </button>
      ))}
    </div>
  );
}
