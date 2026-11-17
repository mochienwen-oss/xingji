import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import styles from './TripsEmptyState.module.css';

const EXAMPLE_CITIES = ['杭州', '泉州', '大理'];

export type TripsEmptyStateProps = {
  onStart: () => void;
  onPickCity: (city: string) => void;
};

/** 我的行程空态：排印海报，不用插画和网络图。 */
export function TripsEmptyState({ onStart, onPickCity }: TripsEmptyStateProps) {
  return (
    <section className={styles.poster} aria-labelledby="trips-empty-title">
      <p className={styles.kicker}>起点</p>
      <h2 className={styles.title} id="trips-empty-title">
        还没有行程
      </h2>
      <p className={styles.body}>选一个城市，说说想怎么玩。第一段路，从地图开始。</p>
      <Button className={styles.cta} onClick={onStart}>
        从地图开始
      </Button>
      <p className={styles.hint}>或者，从这些城市开始</p>
      <ul className={styles.cities}>
        {EXAMPLE_CITIES.map(city => (
          <li key={city}>
            <Chip onClick={() => onPickCity(city)}>{city}</Chip>
          </li>
        ))}
      </ul>
    </section>
  );
}
