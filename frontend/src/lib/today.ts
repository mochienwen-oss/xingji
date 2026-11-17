import type { Day } from '../types/trip';

const DAY_MS = 86_400_000;

/** 行程中的“第几天”索引：只有出发日期存在且今天落在行程区间内才返回。 */
export function todayIndex(
  startDate: string | null | undefined,
  dayCount: number,
  now: Date = new Date(),
): number | null {
  if (!startDate || dayCount <= 0) return null;
  const parts = startDate.split('-').map(Number);
  if (parts.length !== 3 || parts.some(value => !Number.isFinite(value))) return null;
  const [year, month, day] = parts;
  const start = Date.UTC(year, month - 1, day);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const index = Math.round((today - start) / DAY_MS);
  return index >= 0 && index < dayCount ? index : null;
}

/** 本地时间的“当天第几分钟”，用于判断当前走到哪一站。 */
export function minutesSinceMidnight(now: Date = new Date()): number {
  return now.getHours() * 60 + now.getMinutes();
}

export type ScheduledStop = {
  arrival: number | null;
  start: number | null;
  departure: number | null;
};

/**
 * 下一站：当前正在停留时返回后面一站；已走完返回 null；时间缺失时保守返回当前站。
 * 这里只做时间轴判断，不猜测交通或营业时间。
 */
export function nextStopIndex(scheduled: ScheduledStop[], nowMinutes: number): number | null {
  if (scheduled.length === 0) return null;
  for (let index = 0; index < scheduled.length; index += 1) {
    const stop = scheduled[index];
    if (stop.departure == null) return index;
    if (stop.departure < nowMinutes) continue;
    const ongoing = stop.start != null && stop.start <= nowMinutes;
    if (!ongoing) return index;
    return index + 1 < scheduled.length ? index + 1 : null;
  }
  return null;
}

/** 供 TodayCard 使用；单独导出便于测试不同日期/时间组合。 */
export function todayCardModel(
  day: Day,
  scheduled: ScheduledStop[],
  now: Date = new Date(),
): { index: number | null; stop: Day['stops'][number] | null; start: number | null } {
  const index = nextStopIndex(scheduled, minutesSinceMidnight(now));
  if (index == null) return { index: null, stop: null, start: null };
  return {
    index,
    stop: day.stops[index] ?? null,
    start: scheduled[index]?.start ?? scheduled[index]?.arrival ?? null,
  };
}
