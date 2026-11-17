import type { Day, Route, Stop } from '../../types/trip';

const TRANSPORT_LABELS: Record<string, string> = {
  transit: '公交',
  walking: '步行',
  driving: '驾车',
  bicycling: '骑行',
};

export function transportLabel(mode: string | null | undefined): string {
  if (!mode) return '交通';
  return TRANSPORT_LABELS[mode] ?? mode;
}

/** 路线距离：米以下取整，公里保留一位小数。 */
export function formatDistance(distance: number | null | undefined): string | null {
  if (distance == null || !Number.isFinite(distance) || distance < 0) return null;
  if (distance >= 1000) return `${(distance / 1000).toFixed(1)} 公里`;
  return `${Math.round(distance)} 米`;
}

/** 路线耗时（后端单位是秒）→ 分钟，至少 1 分钟。 */
export function formatRouteMinutes(duration: number | null | undefined): string | null {
  if (duration == null || !Number.isFinite(duration) || duration < 0) return null;
  return `${Math.max(1, Math.ceil(duration / 60))} 分钟`;
}

/** 路线段文案：公交 28 分钟 / 3.2 公里；没有路线时返回空串。 */
export function routeText(route: Route | null | undefined, fallbackMode: string): string {
  if (!route) return '';
  const parts = [transportLabel(route.mode || fallbackMode)];
  const duration = formatRouteMinutes(route.duration);
  const distance = formatDistance(route.distance);
  if (duration) parts.push(duration);
  if (distance) parts.push(distance);
  return parts.join(' / ');
}

/** 纯函数排序：越界或原地不动时返回原数组的浅拷贝。 */
export function reorderStops(stops: Stop[], from: number, to: number): Stop[] {
  const next = stops.slice();
  if (from === to || from < 0 || to < 0 || from >= next.length || to >= next.length) return next;
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** 调整站点顺序后路线必失效，一并清空，避免旧路线指向旧顺序。 */
export function reorderDayStops(day: Day, from: number, to: number): Day {
  return { ...day, stops: reorderStops(day.stops, from, to), routes: [] };
}

export function stopTitle(stop: Stop): string {
  return stop.activity?.trim() || stop.place.name;
}

export function dayDateText(index: number, startDate?: string | null): string | null {
  if (!startDate) return null;
  const [year, month, day] = startDate.split('-').map(Number);
  if (!year || !month || !day) return null;
  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) return null;
  date.setDate(date.getDate() + index);
  return `${date.getMonth() + 1}.${date.getDate()}`;
}

export function dayTabLabel(index: number, startDate?: string | null): string {
  const date = dayDateText(index, startDate);
  return date ? `第 ${index + 1} 天 · ${date}` : `第 ${index + 1} 天`;
}


export type TripDiffItem = { day: number; text: string };

/** 保存冲突时只做可读的按天差异，不尝试自动合并。 */
export function diffTripDays(local: Day[], latest: Day[]): TripDiffItem[] {
  const items: TripDiffItem[] = [];
  if (local.length !== latest.length) {
    items.push({ day: 0, text: `天数：你的 ${local.length} 天 → 线上 ${latest.length} 天` });
  }
  const total = Math.max(local.length, latest.length);
  for (let index = 0; index < total; index += 1) {
    const mine = local[index];
    const theirs = latest[index];
    const label = `第 ${index + 1} 天`;
    if (!mine || !theirs) {
      items.push({ day: index + 1, text: `${label} · ${mine ? '你的版本有这一天' : '线上新增了这一天'}` });
      continue;
    }
    const mineIds = mine.stops.map(stop => stop.place.id);
    const theirIds = theirs.stops.map(stop => stop.place.id);
    if (mineIds.join('|') !== theirIds.join('|')) {
      const sameSet = mineIds.length === theirIds.length && [...mineIds].sort().join('|') === [...theirIds].sort().join('|');
      if (sameSet) {
        items.push({ day: index + 1, text: `${label} · 地点顺序不同` });
      } else {
        items.push({ day: index + 1, text: `${label} · 地点 ${mineIds.length} → ${theirIds.length} 个` });
      }
      continue;
    }
    const stopsChanged = mine.stops.some((stop, stopIndex) => {
      const other = theirs.stops[stopIndex];
      return stop.duration !== other.duration || (stop.fixed_time ?? '') !== (other.fixed_time ?? '');
    });
    const timeChanged = (mine.start_time ?? '') !== (theirs.start_time ?? '');
    if (stopsChanged || timeChanged) {
      const parts: string[] = [];
      if (stopsChanged) parts.push('停留或固定时间有调整');
      if (timeChanged) parts.push('出发时间有调整');
      items.push({ day: index + 1, text: `${label} · ${parts.join('，')}` });
    }
  }
  return items;
}


export type TripFieldMerge = 'day' | 'start_time' | 'end_time' | 'duration' | 'fixed_time';

export type TripFieldDiff = {
  id: string;
  /** 展示用：1 开始；0 表示整体（例如天数变化）。 */
  day: number;
  label: string;
  local: string;
  latest: string;
  /** day 表示整天采用线上；其余为单字段；null 表示只能整体取舍。 */
  merge: TripFieldMerge | null;
  dayIndex: number;
  stopId?: string;
};

function timeText(value: string | null | undefined): string {
  return value?.trim() || '未设置';
}

function fixedText(stop: Stop): string {
  const time = stop.fixed_time?.trim();
  if (!time) return '未固定';
  return stop.fixed_next_day ? `${time}（次日）` : time;
}

function durationText(value: number): string {
  return `${Math.max(0, Math.round(value))} 分钟`;
}

function stopNames(stops: Stop[]): string {
  if (stops.length === 0) return '没有地点';
  return stops.map(stop => stopTitle(stop)).join(' → ');
}

/**
 * 保存冲突的可合并差异：天数/地点顺序变化只能整天采用线上；
 * 顺序一致时拆到出发时间、结束时间、每站停留与固定时间。
 */
export function diffTripFields(local: Day[], latest: Day[]): TripFieldDiff[] {
  if (local.length !== latest.length) {
    return [
      {
        id: 'day-count',
        day: 0,
        label: '天数不同',
        local: `${local.length} 天`,
        latest: `${latest.length} 天`,
        merge: null,
        dayIndex: -1,
      },
    ];
  }

  const items: TripFieldDiff[] = [];
  local.forEach((mine, index) => {
    const theirs = latest[index];
    const dayLabel = `第 ${index + 1} 天`;
    const mineIds = mine.stops.map(stop => stop.place.id);
    const theirIds = theirs.stops.map(stop => stop.place.id);

    if (mineIds.join('|') !== theirIds.join('|')) {
      items.push({
        id: `d${index}-plan`,
        day: index + 1,
        label: `${dayLabel} · 地点安排`,
        local: stopNames(mine.stops),
        latest: stopNames(theirs.stops),
        merge: 'day',
        dayIndex: index,
      });
      return;
    }

    if ((mine.start_time ?? '') !== (theirs.start_time ?? '')) {
      items.push({
        id: `d${index}-start`,
        day: index + 1,
        label: `${dayLabel} · 出发时间`,
        local: timeText(mine.start_time),
        latest: timeText(theirs.start_time),
        merge: 'start_time',
        dayIndex: index,
      });
    }
    if ((mine.end_time ?? '') !== (theirs.end_time ?? '')) {
      items.push({
        id: `d${index}-end`,
        day: index + 1,
        label: `${dayLabel} · 结束时间`,
        local: timeText(mine.end_time),
        latest: timeText(theirs.end_time),
        merge: 'end_time',
        dayIndex: index,
      });
    }

    mine.stops.forEach((stop, stopIndex) => {
      const other = theirs.stops[stopIndex];
      if (!other) return;
      if (stop.duration !== other.duration) {
        items.push({
          id: `d${index}-duration-${stop.place.id}`,
          day: index + 1,
          label: `${dayLabel} · ${stopTitle(stop)} · 停留`,
          local: durationText(stop.duration),
          latest: durationText(other.duration),
          merge: 'duration',
          dayIndex: index,
          stopId: stop.place.id,
        });
      }
      if ((stop.fixed_time ?? '') !== (other.fixed_time ?? '') || Boolean(stop.fixed_next_day) !== Boolean(other.fixed_next_day)) {
        items.push({
          id: `d${index}-fixed-${stop.place.id}`,
          day: index + 1,
          label: `${dayLabel} · ${stopTitle(stop)} · 固定时间`,
          local: fixedText(stop),
          latest: fixedText(other),
          merge: 'fixed_time',
          dayIndex: index,
          stopId: stop.place.id,
        });
      }
    });
  });

  return items;
}

function cloneDay(day: Day): Day {
  return {
    ...day,
    stops: day.stops.map(stop => ({ ...stop, place: { ...stop.place } })),
    routes: day.routes.map(route => ({ ...route, polyline: route.polyline.map(line => line.slice()) })),
  };
}

/** 以本地为底，套用勾选的线上字段；未勾选或不可合并的差异保持本地。 */
export function mergeTripDays(local: Day[], latest: Day[], selectedIds: Iterable<string>): Day[] {
  const diffs = new Map(diffTripFields(local, latest).map(diff => [diff.id, diff]));
  const merged = local.map(cloneDay);
  for (const id of selectedIds) {
    const diff = diffs.get(id);
    if (!diff || !diff.merge) continue;
    const target = merged[diff.dayIndex];
    const source = latest[diff.dayIndex];
    if (!target || !source) continue;

    if (diff.merge === 'day') {
      merged[diff.dayIndex] = cloneDay(source);
      continue;
    }
    if (diff.merge === 'start_time') {
      target.start_time = source.start_time ?? null;
      continue;
    }
    if (diff.merge === 'end_time') {
      target.end_time = source.end_time ?? null;
      continue;
    }
    if (!diff.stopId) continue;
    const stopIndex = target.stops.findIndex(stop => stop.place.id === diff.stopId);
    const sourceStop = source.stops.find(stop => stop.place.id === diff.stopId);
    if (stopIndex < 0 || !sourceStop) continue;
    if (diff.merge === 'duration') target.stops[stopIndex].duration = sourceStop.duration;
    if (diff.merge === 'fixed_time') {
      target.stops[stopIndex].fixed_time = sourceStop.fixed_time ?? null;
      target.stops[stopIndex].fixed_next_day = sourceStop.fixed_next_day;
    }
  }
  return merged;
}

export function totalStops(days: Day[]): number {
  return days.reduce((sum, day) => sum + day.stops.length, 0);
}

export function initialOf(username: string): string {
  const trimmed = username.trim();
  return trimmed ? Array.from(trimmed)[0].toUpperCase() : '?';
}