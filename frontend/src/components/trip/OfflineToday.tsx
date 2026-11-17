import type { CachedToday } from '../../lib/todayCache';
import { AiNotice } from '../ui/AiNotice';
import styles from './OfflineToday.module.css';

type Props = {
  cache: CachedToday;
  retrying: boolean;
  onRetry: () => void;
  onBack: () => void;
};

function stamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '上次';
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${month} 月 ${day} 日 ${hour}:${minute}`;
}

/** 断网或接口不可达时的只读兜底：只展示本机缓存的“今天”，不提供编辑与保存。 */
export function OfflineToday({ cache, retrying, onRetry, onBack }: Props) {
  const title = cache.title || `${cache.city}行程`;
  return (
    <main className={styles.page}>
      <header className={styles.top}>
        <button type="button" className={styles.back} onClick={onBack} aria-label="返回我的行程">
          <span aria-hidden="true">←</span> 我的行程
        </button>
        <span className={styles.kicker}>离线 · 今日行程</span>
      </header>

      <section className={styles.summary} aria-labelledby="offline-today-title">
        <p className={styles.notice} role="status">
          当前离线，显示 {stamp(cache.savedAt)} 缓存的本机版本。联网后可以继续编辑。
        </p>
        <h1 id="offline-today-title" className={styles.title}>{title}</h1>
        <p className={styles.meta}>
          {cache.city} · 第 {cache.dayIndex + 1} 天 · {cache.stops.length} 个地点
        </p>
      </section>

      <AiNotice>离线快照由 AI 生成，地点与时间请在出发前核实。</AiNotice>

      {cache.stops.length > 0 ? (
        <ol className={styles.stops} aria-label="今日地点">
          {cache.stops.map((stop, index) => (
            <li key={`${stop.name}-${index}`} className={styles.stop}>
              <span className={styles.index} aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
              <div className={styles.stopBody}>
                <strong className={styles.stopName}>{stop.name}</strong>
                {stop.address ? <span className={styles.address}>{stop.address}</span> : null}
                <span className={styles.stopMeta}>
                  {stop.time ? `预计 ${stop.time} 到` : '时间待定'}
                  {stop.duration ? ` · 停留 ${stop.duration} 分钟` : ''}
                </span>
              </div>
              {stop.navigationUrl ? (
                <a
                  className={styles.nav}
                  href={stop.navigationUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label={`导航到${stop.name}`}
                >
                  导航
                </a>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.empty}>缓存的这一天还没有地点。</p>
      )}

      <div className={styles.actions}>
        <button type="button" className={styles.retry} onClick={onRetry} disabled={retrying}>
          {retrying ? '正在重连…' : '重新连接'}
        </button>
      </div>
      <p className={styles.footnote}>导航按钮会唤起高德地图；离线时可能无法打开。修改请等联网后回到行程页。</p>
    </main>
  );
}
