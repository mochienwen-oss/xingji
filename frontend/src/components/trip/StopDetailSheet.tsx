import { useEffect, useState } from 'react';
import type { Stop } from '../../types/trip';
import { useConfirm } from '../../app/providers/ToastProvider';
import { Button } from '../ui/Button';
import { Sheet } from '../ui/Sheet';
import { TextField } from '../ui/TextField';
import { amapNavigationUrl, navigationMode } from '../../lib/amapNavigation';
import { stopTitle } from './workspace';
import styles from './TripWorkspace.module.css';

type Props = {
  open: boolean;
  stop: Stop | null;
  index: number;
  total: number;
  busy: boolean;
  transport: string;
  onClose: () => void;
  onDuration: (minutes: number) => void;
  onFixedTime: (value: string | null, nextDay: boolean) => void;
  onMove: (delta: number) => void;
  onDelete: () => void;
};

/** 地点详情抽屉：改停留时长、固定时间、上下移动或移除。 */
export function StopDetailSheet({
  open,
  stop,
  index,
  total,
  busy,
  transport,
  onClose,
  onDuration,
  onFixedTime,
  onMove,
  onDelete,
}: Props) {
  const confirm = useConfirm();
  const [detent, setDetent] = useState<'peek' | 'half' | 'full'>('half');
  const [duration, setDuration] = useState('90');
  const [durationError, setDurationError] = useState('');
  const [fixedOn, setFixedOn] = useState(false);
  const [fixedTime, setFixedTime] = useState('09:00');
  const [fixedNextDay, setFixedNextDay] = useState(false);
  const [fixedError, setFixedError] = useState('');
  const navUrl = stop ? amapNavigationUrl(stop.place, navigationMode(transport)) : null;

  useEffect(() => {
    setDuration(String(stop?.duration ?? 90));
    setDurationError('');
    setFixedOn(!!stop?.fixed_time);
    setFixedTime(stop?.fixed_time || '09:00');
    setFixedNextDay(!!stop?.fixed_next_day);
    setFixedError('');
  }, [stop?.place.id, stop?.duration, stop?.fixed_time, stop?.fixed_next_day]);

  function saveDuration() {
    const value = Number(duration);
    if (!Number.isInteger(value) || value < 15 || value > 480) {
      setDurationError('请输入 15–480 之间的整数分钟。');
      return;
    }
    setDurationError('');
    onDuration(value);
  }

  function saveFixedTime() {
    if (fixedOn && !fixedTime) {
      setFixedError('请选择固定时间。');
      return;
    }
    setFixedError('');
    onFixedTime(fixedOn ? fixedTime : null, fixedOn ? fixedNextDay : false);
  }

  async function remove() {
    if (!stop) return;
    const ok = await confirm({
      title: '从这一天移除这个地点？',
      body: `「${stopTitle(stop)}」会从当前安排中移除，想保留可以先取消。`,
      confirmLabel: '移除',
      danger: true,
    });
    if (ok) onDelete();
  }

  return (
    <Sheet open={open && !!stop} detent={detent} onDetentChange={setDetent} onClose={onClose} labelledBy="stop-detail-title">
      <div className={styles.stopDetail}>
        <h2 id="stop-detail-title" className={styles.sheetTitle}>
          {stop ? stopTitle(stop) : '地点详情'}
        </h2>
        {stop ? (
          <>
            <p className={styles.sheetHint}>
              {stop.place.name}
              {stop.place.address ? ` · ${stop.place.address}` : ''}
            </p>

            <div className={styles.detailBlock}>
              <span className={styles.detailLabel}>去这里</span>
              {navUrl ? (
                <a className={styles.navLink} href={navUrl} target="_blank" rel="noreferrer noopener">
                  在高德地图中导航
                </a>
              ) : (
                <p className={styles.sheetHint}>这个地点缺少坐标，暂时无法导航。</p>
              )}
            </div>

            <div className={styles.detailBlock}>
              <TextField
                label="停留时长（分钟）"
                type="number"
                min={15}
                max={480}
                step={5}
                value={duration}
                error={durationError}
                onChange={event => setDuration(event.target.value)}
              />
              <Button variant="secondary" onClick={saveDuration} disabled={busy}>
                保存停留时长
              </Button>
            </div>

            <div className={styles.detailBlock}>
              <label className={styles.checkRow}>
                <input
                  type="checkbox"
                  checked={fixedOn}
                  onChange={event => {
                    setFixedOn(event.target.checked);
                    if (!event.target.checked) setFixedNextDay(false);
                    setFixedError('');
                  }}
                />
                <span>固定到具体时间</span>
              </label>
              <label className={styles.checkRow}>
                <input
                  type="checkbox"
                  checked={fixedNextDay}
                  disabled={!fixedOn}
                  onChange={event => setFixedNextDay(event.target.checked)}
                />
                <span>次日（凌晨）</span>
              </label>
              <TextField
                label="固定时间"
                type="time"
                value={fixedTime}
                disabled={!fixedOn}
                error={fixedError}
                onChange={event => setFixedTime(event.target.value)}
              />
              <Button variant="secondary" onClick={saveFixedTime} disabled={busy}>
                保存固定时间
              </Button>
            </div>

            <div className={styles.detailBlock}>
              <span className={styles.detailLabel}>调整顺序</span>
              <div className={styles.detailActions}>
                <Button variant="secondary" onClick={() => onMove(-1)} disabled={busy || index <= 0}>
                  上移
                </Button>
                <Button variant="secondary" onClick={() => onMove(1)} disabled={busy || index >= total - 1}>
                  下移
                </Button>
              </div>
            </div>

            <div className={styles.detailFooter}>
              <Button variant="danger" onClick={remove} disabled={busy}>
                从这一天移除
              </Button>
            </div>
          </>
        ) : (
          <p className={styles.sheetHint}>这个地点已经不在当前安排中。</p>
        )}
      </div>
    </Sheet>
  );
}
