import type { Day } from '../../types/trip';
import { amapNavigationUrl, navigationMode } from '../../lib/amapNavigation';
import { formatTime } from '../../lib/schedule';
import { todayCardModel, type ScheduledStop } from '../../lib/today';
import styles from './TripWorkspace.module.css';

type Props = {
  day: Day;
  dayIndex: number;
  scheduled: ScheduledStop[];
  transport: string;
  active: boolean;
  now: Date;
  onSelect: () => void;
  onAddPlace: () => void;
};

/** 行中只读卡：今天第几天、下一站、导航与临时加地点。 */
export function TodayCard({ day, dayIndex, scheduled, transport, active, now, onSelect, onAddPlace }: Props) {
  const model = todayCardModel(day, scheduled, now);
  const next = model.stop;
  const finished = day.stops.length > 0 && model.index == null;
  const navUrl = next ? amapNavigationUrl(next.place, navigationMode(transport)) : null;
  const timeLabel = model.start != null ? `预计 ${formatTime(model.start)} 到` : '时间待定';

  return (
    <section className={styles.todayCard} aria-label="今天的行程">
      <div className={styles.todayTop}>
        <span className={styles.todayKicker}>今天 · 第 {dayIndex + 1} 天</span>
        <div className={styles.todayTools}>
          <span className={styles.todayCount}>{day.stops.length} 个地点</span>
          <button type="button" className={styles.todayTextButton} onClick={onAddPlace}>
            加地点
          </button>
          {!active ? (
            <button type="button" className={styles.todayTextButton} onClick={onSelect}>
              看今天
            </button>
          ) : null}
        </div>
      </div>
      <div className={styles.todayMain}>
        <div className={styles.todayInfo}>
          {next ? <span className={styles.todayLabel}>下一站</span> : null}
          <strong className={styles.todayName}>
            {next ? next.place.name : finished ? '今天的安排已结束' : '今天还没有安排地点'}
          </strong>
          {next ? <span className={styles.todayTime}>{timeLabel}</span> : null}
        </div>
        {next && navUrl ? (
          <a
            className={styles.todayNav}
            href={navUrl}
            target="_blank"
            rel="noreferrer noopener"
            aria-label={`导航到${next.place.name}`}
          >
            导航
          </a>
        ) : null}
      </div>
    </section>
  );
}
