import type { Place } from '../../types/trip';
import { TrashIcon } from '../icons';
import styles from './SavedPlacesList.module.css';

export type SavedPlacesListProps = {
  places: Place[];
  onSelect: (place: Place) => void;
  onRemove: (place: Place) => void;
};

export function SavedPlacesList({ places, onSelect, onRemove }: SavedPlacesListProps) {
  if (!places.length) {
    return (
      <p className={styles.empty}>
        收藏夹还是空的。把想去的地方加进来，规划时会优先安排。
      </p>
    );
  }

  return (
    <ul className={styles.list}>
      {places.map((place) => (
        <li key={place.id} className={styles.row}>
          <button
            type="button"
            className={styles.main}
            aria-label={`查看收藏${place.name}`}
            onClick={() => onSelect(place)}
          >
            <span className={styles.name}>{place.name}</span>
            <span className={styles.meta}>
              {place.city || '未标注城市'}
              {place.address ? ` · ${place.address}` : ''}
              {place.unavailable ? ' · 地点信息暂不可用' : ''}
            </span>
          </button>
          <button
            type="button"
            className={styles.remove}
            aria-label={`移除收藏${place.name}`}
            title="移除收藏"
            onClick={() => onRemove(place)}
          >
            <TrashIcon size={18} />
          </button>
        </li>
      ))}
    </ul>
  );
}
