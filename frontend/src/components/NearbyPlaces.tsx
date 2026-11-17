import { useEffect, useState } from 'react';
import { api, message } from '../lib/api';
import type { Day, Place } from '../types/trip';
import { PlaceThumbnail } from './PlaceThumbnail';
import { Button } from './ui/Button';
import styles from './NearbyPlaces.module.css';

type Props = {
  tripId: number;
  dayIndex: number;
  day: Day;
  dirty: boolean;
  existingIds: string[];
  onAdd: (place: Place, anchorId: string) => void;
};

const CATEGORIES = ['餐厅', '咖啡', '景点'];

/**
 * 行程内的附近探索。抽屉本身就是「附近地点」，所以内容直接展开，
 * 不再套一层「探索附近地点」的折叠开关——多一次点击只会让人以为这里是空的。
 */
export function NearbyPlaces({ tripId, dayIndex, day, dirty, existingIds, onAdd }: Props) {
  const firstStop = day.stops[0]?.place.id ?? '';
  const [anchor, setAnchor] = useState(firstStop);
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [results, setResults] = useState<Place[]>([]);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!day.stops.some(stop => stop.place.id === anchor)) setAnchor(day.stops[0]?.place.id ?? '');
  }, [day, anchor]);

  async function search() {
    if (!anchor || dirty || busy) return;
    setBusy(true);
    setError('');
    setResults([]);
    setSearched(false);
    try {
      const found = await api<Place[]>(
        `/trips/${tripId}/days/${dayIndex}/nearby?place_id=${encodeURIComponent(anchor)}&category=${encodeURIComponent(category)}`,
      );
      setResults(found);
      setSearched(true);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!day.stops.length) {
    return <p className={styles.empty}>这一天还没有地点，先从待规划里添加一个，再探索附近。</p>;
  }

  return (
    <div className={styles.root}>
      <p className={styles.lede}>以今天已安排的地点为中心，搜索约 2 公里内还能顺路去的地方。</p>
      <div className={styles.form}>
        <label className={styles.field}>
          <span>中心地点</span>
          <select
            className={styles.select}
            value={anchor}
            disabled={busy}
            onChange={event => { setAnchor(event.target.value); setResults([]); setSearched(false); }}
          >
            {day.stops.map(stop => (
              <option key={stop.place.id} value={stop.place.id}>{stop.place.name}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>想找什么</span>
          <select
            className={styles.select}
            value={category}
            disabled={busy}
            onChange={event => { setCategory(event.target.value); setResults([]); setSearched(false); }}
          >
            {CATEGORIES.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <Button className={styles.search} loading={busy} disabled={dirty || !anchor} onClick={() => void search()}>
          {busy ? '搜索中…' : '搜索附近'}
        </Button>
      </div>
      {dirty ? <p className={styles.hint}>先保存当前修改，再搜索附近地点。</p> : null}
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {searched && !results.length ? <p className={styles.hint}>附近暂无结果，换个中心地点或类型试试。</p> : null}
      {results.length ? (
        <ul className={styles.results}>
          {results.map(place => {
            const added = existingIds.includes(place.id);
            const distance = typeof place.distance === 'number'
              ? place.distance < 1000 ? `${Math.round(place.distance)} 米` : `${(place.distance / 1000).toFixed(1)} 公里`
              : '';
            return (
              <li key={place.id} className={styles.result}>
                <PlaceThumbnail place={place} />
                <div className={styles.info}>
                  <strong className={styles.name}>{place.name}</strong>
                  <span className={styles.address}>{place.address || '地址暂无信息'}</span>
                  {distance ? <span className={styles.distance}>直线约 {distance}</span> : null}
                </div>
                <Button
                  variant="secondary"
                  className={styles.add}
                  disabled={busy || added}
                  onClick={() => onAdd(place, anchor)}
                >
                  {added ? '已在行程' : `加入第 ${dayIndex + 1} 天`}
                </Button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {results.length ? <p className={styles.notice}>距离是地图直线距离，不代表步行或乘车顺路；加入后保存才会更新路线。</p> : null}
    </div>
  );
}
