import type { Trip } from '../../types/trip';
import { AiNotice } from '../ui/AiNotice';
import { Button } from '../ui/Button';
import { Kicker } from '../ui/Kicker';
import { Sheet } from '../ui/Sheet';
import styles from './PreviewSheet.module.css';

export type PreviewSheetProps = {
  preview: Trip | null;
  open: boolean;
  saved: boolean;
  saving: boolean;
  error: string;
  onClose: () => void;
  onSave: () => void;
};

export function PreviewSheet({ preview, open, saved, saving, error, onClose, onSave }: PreviewSheetProps) {
  return (
    <Sheet
      open={open}
      detent="full"
      onDetentChange={() => undefined}
      onClose={onClose}
      labelledBy="explore-preview-title"
    >
      <div className={styles.body}>
        <Kicker>行程预览</Kicker>
        <h2 id="explore-preview-title" className={styles.title}>
          {preview?.request.city ? `${preview.request.city}的路线` : '你的路线'}
        </h2>
        <p className={styles.summary}>
          {preview ? `${preview.days.length} 天 · ${preview.days.reduce((sum, day) => sum + day.stops.length, 0)} 个地点` : '还没有生成内容'}
        </p>
        <AiNotice>行程由 AI 生成，地点与时间请在出发前核实。</AiNotice>
        {preview?.place_notice ? <p className={styles.notice}>{preview.place_notice}</p> : null}
        <div className={styles.days}>
          {preview?.days.map((day, dayIndex) => (
            <section key={dayIndex} className={styles.day} aria-labelledby={`explore-preview-day-${dayIndex}`}>
              <h3 id={`explore-preview-day-${dayIndex}`} className={styles.dayTitle}>第 {dayIndex + 1} 天</h3>
              {day.stops.length ? (
                <ol className={styles.stops}>
                  {day.stops.map((stop, stopIndex) => (
                    <li key={`${stop.place.id}-${stopIndex}`} className={styles.stop}>
                      <span className={styles.stopIndex}>{stopIndex + 1}</span>
                      <span className={styles.stopBody}>
                        <span className={styles.stopName}>{stop.place.name}</span>
                        <span className={styles.stopMeta}>
                          {[stop.duration, stop.reason].filter(Boolean).join(' · ') || '停留时间可调整'}
                        </span>
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className={styles.dayEmpty}>这一天还没有安排地点。</p>
              )}
            </section>
          ))}
        </div>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        <div className={styles.actions}>
          <Button variant="primary" size="lg" loading={saving} disabled={saved || !preview} onClick={onSave}>
            {saved ? '已保存' : '保存行程'}
          </Button>
          <Button variant="text" size="md" onClick={onClose}>继续调整</Button>
        </div>
      </div>
    </Sheet>
  );
}
