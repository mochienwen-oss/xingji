import type { Day } from "../types/trip";

const TIME_PATTERN = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** 解析 HH:MM；非法格式返回 null，避免把 NaN 带进时间线。 */
function minutes(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const match = TIME_PATTERN.exec(value.trim());
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

export function formatTime(value: number): string {
  const day = Math.floor(value / 1440);
  const minute = value % 1440;
  return `${day === 1 ? '次日 ' : day > 1 ? `+${day}天 ` : ''}${String(Math.floor(minute / 60)).padStart(2,'0')}:${String(minute % 60).padStart(2,'0')}`;
}

export function formatRange(start: number | null, end: number | null): string | null {
  if (start == null || end == null) return null;
  return `${formatTime(start)}–${formatTime(end)}`;
}

/** 把固定时刻连同「次日」标记格式化成时间线文案；没有有效时间时返回空串，由调用方显示待定。 */
export function formatFixedTime(fixedTime: string | null | undefined, nextDay: boolean): string {
  const value = minutes(fixedTime);
  if (value == null) return '';
  return formatTime(value + (nextDay ? 1440 : 0));
}

/** 每段换乘留出的机动时间；不改变路线本身，只让到达时间更接近真实情况。 */
export const TRANSFER_BUFFER_MINUTES = 10;

/** 结束时间与用户设定的最晚结束时间对比；没有路线/停留信息时不编造。 */
export function finishText(finish: number | null, deadline: number | null, buffer = 0): string | null {
  if (finish == null) return null;
  const bufferText = buffer > 0 ? `（含 ${buffer} 分钟机动）` : '';
  const base = `预计 ${formatTime(finish)} 结束${bufferText}`;
  return deadline != null && finish > deadline ? `${base}，晚于 ${formatTime(deadline)}` : base;
}

export function scheduleDay(day: Day, mode: string) {
  const startAt = minutes(day.start_time);
  // 开始时间缺失或写坏时不排任何时间，页面按「待定」展示。
  if (startAt == null) return {stops: [], finish: null, deadline: null, incomplete: false, buffer: 0};
  let current: number | null = startAt;
  const end = minutes(day.end_time);
  const deadline = end == null ? null : end + (end <= startAt ? 1440 : 0);
  let buffer = 0;
  const stops = day.stops.map((stop, index) => {
    if (index > 0 && current !== null) {
      const route = day.routes[index-1];
      const previous = day.stops[index-1];
      // 只有高德返回、且交通方式与起终点都匹配本天的路段才是精确耗时。
      const exact = route != null && route.duration != null && route.origin === previous.place.id && route.destination === stop.place.id && route.mode === mode;
      if (exact && route && route.duration != null) {
        current += Math.ceil(route.duration / 60) + TRANSFER_BUFFER_MINUTES;
        buffer += TRANSFER_BUFFER_MINUTES;
      } else {
        // 缺少本段耗时：需求要求后续时间显示待定，不能拿直线距离编造。
        current = null;
      }
    }
    const arrival: number | null = current;
    const fixedMinutes = minutes(stop.fixed_time);
    const fixed = fixedMinutes == null ? null : fixedMinutes + (stop.fixed_next_day ? 1440 : 0);
    const late = current !== null && fixed !== null && current > fixed;
    if (current !== null && fixed !== null && current < fixed) current = fixed;
    const start: number | null = current;
    if (current !== null && Number.isInteger(stop.duration) && stop.duration >= 15 && stop.duration <= 480) current += stop.duration;
    else current = null;
    return {arrival, start, departure: current, fixed, late};
  });
  return {
    stops,
    finish: day.stops.length ? current : null,
    deadline,
    incomplete: day.stops.length > 0 && current === null,
    buffer,
  };
}
