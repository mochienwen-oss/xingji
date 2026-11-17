import { useEffect, useState } from 'react';
import type { Place } from '../../types/trip';
import { Button } from '../ui/Button';
import { Sheet } from '../ui/Sheet';
import { amapNavigationUrl } from '../../lib/amapNavigation';
import type { SheetDetent } from '../../lib/useSheetDrag';
import styles from './PlaceDetailSheet.module.css';

export type PlaceDetailSheetProps = {
  place: Place | null;
  open: boolean;
  /** 已加入当前预览行程（决定「加入行程」是否可用）。 */
  saved: boolean;
  /** 已收藏到待规划池（决定次按钮显示「收藏」还是「取消收藏」）。 */
  collected: boolean;
  onClose: () => void;
  onAdd: (place: Place) => void;
  onToggle: (place: Place) => void;
};

export function PlaceDetailSheet({ place, open, saved, collected, onClose, onAdd, onToggle }: PlaceDetailSheetProps) {
  const [detent, setDetent] = useState<SheetDetent>('half');
  const [hoursOpen, setHoursOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDetent('half');
    setHoursOpen(false);
  }, [open, place?.id]);

  return (
    <Sheet
      open={open}
      detent={detent}
      onDetentChange={setDetent}
      onClose={onClose}
      labelledBy="explore-place-title"
      footer={
        place ? (
          <div className={styles.actions}>
            <Button
              variant="primary"
              size="lg"
              disabled={saved || place.unavailable}
              onClick={() => onAdd(place)}
            >
              {saved ? '已加入行程' : '加入行程'}
            </Button>
            <Button variant="secondary" size="lg" onClick={() => onToggle(place)}>
              {collected ? '取消收藏' : '收藏'}
            </Button>
          </div>
        ) : null
      }
    >
      <div className={styles.body}>
        <h2 id="explore-place-title" className={styles.title}>{place?.name || '地点详情'}</h2>
        {place ? (
          <>
            <p className={styles.address}>{place.address || '地址以地图为准'}</p>
            {amapNavigationUrl(place) ? (
              <a
                className={styles.navigate}
                href={amapNavigationUrl(place) ?? undefined}
                target="_blank"
                rel="noreferrer noopener"
              >
                在高德地图中导航
              </a>
            ) : null}
            <dl className={styles.meta}>
              <div className={styles.metaRow}>
                <dt>开放时间</dt>
                <dd>
                  <span className={hoursOpen ? styles.hoursOpen : styles.hoursClamp}>
                    {place.opentime || '以现场为准'}
                  </span>
                  {place.opentime && place.opentime.length > 30 ? (
                    <button
                      type="button"
                      className={styles.more}
                      aria-expanded={hoursOpen}
                      onClick={() => setHoursOpen((value) => !value)}
                    >
                      {hoursOpen ? '收起' : '展开全部'}
                    </button>
                  ) : null}
                </dd>
              </div>
              <div className={styles.metaRow}>
                <dt>票价</dt>
                <dd>{place.cost || '以现场为准'}</dd>
              </div>
              {place.city ? (
                <div className={styles.metaRow}>
                  <dt>城市</dt>
                  <dd>{place.city}</dd>
                </div>
              ) : null}
            </dl>
            {place.unavailable ? (
              <p className={styles.notice}>这个地点的详细信息暂时不可用，仍可在对话里提到它。</p>
            ) : null}
          </>
        ) : null}
      </div>
    </Sheet>
  );
}