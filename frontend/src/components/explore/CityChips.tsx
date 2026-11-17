import { Chip } from '../ui/Chip';
import styles from './CityChips.module.css';

export type CityChipsProps = {
  cities: string[];
  selected: string;
  loading: boolean;
  onSelect: (city: string) => void;
  /** 换一批：不传时隐藏入口。 */
  onRefresh?: () => void;
};

export function CityChips({ cities, selected, loading, onSelect, onRefresh }: CityChipsProps) {
  return (
    <div className={styles.root}>
      <div className={styles.chips} role="group" aria-label="热门城市">
        {cities.map((city) => (
          <Chip
            key={city}
            selected={selected === city}
            disabled={loading}
            onClick={() => onSelect(city)}
          >
            {city}
          </Chip>
        ))}
        {onRefresh ? (
          <Chip disabled={loading} onClick={onRefresh}>换一批</Chip>
        ) : null}
      </div>
      {loading ? <span className={styles.status} role="status">正在找这座城市…</span> : null}
    </div>
  );
}
