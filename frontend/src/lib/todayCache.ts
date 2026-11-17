import type { Day, Trip } from '../types/trip';
import { amapNavigationUrl, navigationMode } from './amapNavigation';
import { formatTime, scheduleDay } from './schedule';
import { todayIndex } from './today';

const KEY_PREFIX = 'xingji.today.v1.';
const MAX_STOPS = 40;
const MAX_NAME = 80;
const MAX_ADDRESS = 200;

/** 地点名缺失时写入的占位文案；离线快照与草稿恢复共用，保证写进去的快照读得回来。 */
export const PLACE_NAME_UNAVAILABLE = '地点信息暂不可用';

export type CachedTodayStop = {
  name: string;
  address: string;
  time: string | null;
  duration: number;
  navigationUrl: string | null;
};

export type CachedToday = {
  v: 1;
  tripId: number;
  title: string;
  city: string;
  startDate: string;
  dayIndex: number;
  transport: string;
  savedAt: string;
  stops: CachedTodayStop[];
};

function storage(): Storage | null {
  try {
    if (typeof window === 'undefined') return null;
    return window.localStorage;
  } catch {
    // 隐私模式或站点数据被禁用时 localStorage 会抛错，缓存失败不应影响行程。
    return null;
  }
}

function clean(value: unknown, max: number): string {
  return typeof value === 'string' ? value.trim().slice(0, max) : '';
}

function normalize(value: unknown): CachedToday | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (raw.v !== 1) return null;
  if (!Number.isInteger(raw.tripId) || !Number.isInteger(raw.dayIndex)) return null;
  if (typeof raw.startDate !== 'string' || typeof raw.savedAt !== 'string') return null;
  if (!Array.isArray(raw.stops) || raw.stops.length > MAX_STOPS) return null;

  const stops: CachedTodayStop[] = [];
  for (const item of raw.stops) {
    if (!item || typeof item !== 'object') return null;
    const stop = item as Record<string, unknown>;
    const name = clean(stop.name, MAX_NAME);
    if (!name) return null;
    stops.push({
      name,
      address: clean(stop.address, MAX_ADDRESS),
      time: typeof stop.time === 'string' && stop.time.length <= 24 ? stop.time : null,
      duration: Number.isFinite(stop.duration) ? Number(stop.duration) : 0,
      navigationUrl: typeof stop.navigationUrl === 'string' && stop.navigationUrl.startsWith('https://uri.amap.com/')
        ? stop.navigationUrl
        : null,
    });
  }

  return {
    v: 1,
    tripId: Number(raw.tripId),
    title: clean(raw.title, MAX_NAME),
    city: clean(raw.city, MAX_NAME),
    startDate: raw.startDate.slice(0, 10),
    dayIndex: Number(raw.dayIndex),
    transport: clean(raw.transport, 24),
    savedAt: raw.savedAt.slice(0, 40),
    stops,
  };
}

/** 只缓存“今天”这一天的只读快照，不缓存完整行程、同行人或对话。 */
export function buildTodayCache(
  trip: Trip,
  dayIndex: number,
  day: Day,
  now: Date = new Date(),
): CachedToday | null {
  if (!trip.request.start_date || dayIndex < 0) return null;
  // 只缓存“今天”这一天：跨零点或行程未开始/已结束时写进去也会被 readTodayCache 丢弃。
  if (todayIndex(trip.request.start_date, dayIndex + 1, now) !== dayIndex) return null;
  const schedule = scheduleDay(day, trip.request.transport);
  const mode = navigationMode(trip.request.transport);
  return {
    v: 1,
    tripId: trip.id,
    title: clean(trip.title, MAX_NAME),
    city: clean(trip.request.city, MAX_NAME),
    startDate: trip.request.start_date,
    dayIndex,
    transport: trip.request.transport,
    savedAt: now.toISOString(),
    stops: day.stops.slice(0, MAX_STOPS).map((stop, index) => ({
      // normalize 会把空名整份快照判为损坏；空名必须写占位，否则缓存永远读不回来。
      name: clean(stop.place.name, MAX_NAME) || PLACE_NAME_UNAVAILABLE,
      address: clean(stop.place.address, MAX_ADDRESS),
      time: schedule.stops[index]?.start != null ? formatTime(schedule.stops[index].start as number) : null,
      duration: stop.duration,
      navigationUrl: amapNavigationUrl(stop.place, mode),
    })),
  };
}

export function saveTodayCache(
  trip: Trip,
  dayIndex: number,
  day: Day,
  now: Date = new Date(),
): CachedToday | null {
  const cache = buildTodayCache(trip, dayIndex, day, now);
  if (!cache) return null;
  const target = storage();
  if (!target) return null;
  try {
    target.setItem(KEY_PREFIX + cache.tripId, JSON.stringify(cache));
    return cache;
  } catch {
    // 配额满或浏览器拒绝写入时静默降级，联网页面照常使用。
    return null;
  }
}

/** 只读取“今天仍然有效”的快照；日期已过、行程换日期或数据损坏都返回 null。 */
export function readTodayCache(tripId: number, now: Date = new Date()): CachedToday | null {
  const target = storage();
  if (!target) return null;
  try {
    const raw = target.getItem(KEY_PREFIX + tripId);
    if (!raw) return null;
    const cache = normalize(JSON.parse(raw));
    if (!cache || cache.tripId !== tripId) return null;
    if (todayIndex(cache.startDate, cache.dayIndex + 1, now) !== cache.dayIndex) return null;
    return cache;
  } catch {
    return null;
  }
}

export function clearAllTodayCaches(): void {
  const target = storage();
  if (!target) return;
  try {
    const keys: string[] = [];
    for (let index = 0; index < target.length; index += 1) {
      const key = target.key(index);
      if (key?.startsWith(KEY_PREFIX)) keys.push(key);
    }
    for (const key of keys) target.removeItem(key);
  } catch {
    // 存储不可用时无需清理。
  }
}
