import { useId } from 'react';
import type { PlazaTrip } from '../../types/trip';
import { ArrowRightIcon } from '../icons';
import { TripCover } from '../trip/TripCover';
import styles from './PlazaCard.module.css';
import { formatTripDate, tripName } from './tripMeta';

export type PlazaCardProps = {
  trip: PlazaTrip;
  onFork: (trip: PlazaTrip) => void;
  onReport?: (trip: PlazaTrip) => void;
};

/** 广场卡片：封面 + 标题 + 作者/天数/日期；整卡点击进入复制确认。 */
export function PlazaCard({ trip, onFork, onReport }: PlazaCardProps) {
  const id = useId();
  const titleId = id + '-title';
  const actionId = id + '-action';
  const name = tripName(trip);
  const date = formatTripDate(trip.start_date);

  return (
    <article className={styles.card}>
      <div className={styles.media}>
        <TripCover city={trip.city} />
      </div>
      <div className={styles.text}>
        <h2 className={styles.title} id={titleId}>
          {name}
        </h2>
        <p className={styles.meta}>
          {[trip.owner, trip.days + ' 天', date || '日期待定'].filter(Boolean).join(' · ')}
        </p>
        <p className={styles.action} id={actionId}>
          复制到我的行程
          <ArrowRightIcon size={16} />
        </p>
      </div>
      <button
        type="button"
        className={styles.hit}
        aria-labelledby={titleId}
        aria-describedby={actionId}
        onClick={() => onFork(trip)}
      />
      {onReport ? (
        <button
          type="button"
          className={styles.report}
          aria-label={'举报行程：' + name}
          onClick={() => onReport(trip)}
        >
          举报
        </button>
      ) : null}
    </article>
  );
}
