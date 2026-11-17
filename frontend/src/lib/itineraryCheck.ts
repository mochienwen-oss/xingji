import type { Day, Place, Stop } from "../types/trip";
import { distanceKmBetween } from "./geo";

export type HealthLang = "zh" | "en";

export type TripHealthInput = {
  days: Day[];
  request?: { start_date?: string | null } | null;
  backlog?: Stop[] | null;
};

export type ClosedDayCheck = {
  code: "closed_day";
  severity: "warning";
  day: number;
  place: string;
  weekday: number;
};

export type WeeklyClosureCheck = {
  code: "weekly_closure";
  severity: "info";
  places: { name: string; closedDays: number[] }[];
};

export type LongHopCheck = {
  code: "long_hop";
  severity: "warning";
  day: number;
  from: string;
  to: string;
  km: number;
};

export type HeavyDayCheck = {
  code: "heavy_day";
  severity: "warning";
  day: number;
  stops: number;
  minutes: number;
};

export type DuplicatePlaceCheck = {
  code: "duplicate_place";
  severity: "info";
  name: string;
  count: number;
};

export type ItineraryCheck =
  | ClosedDayCheck
  | WeeklyClosureCheck
  | LongHopCheck
  | HeavyDayCheck
  | DuplicatePlaceCheck;

const ALL_DAYS = [1, 2, 3, 4, 5, 6, 7];
const WEEKDAY_INDEX: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  日: 7,
  天: 7,
};

/** 周一=1 … 周日=7，避免 JS Date 把周日算成 0。 */
export function weekdayMon(date: Date): number {
  const day = date.getDay();
  return day === 0 ? 7 : day;
}

/** start_date 只取日期部分，按本地时区加天；无日期/格式异常返回 null。 */
export function startDateForDay(value: string | null | undefined, dayIndex: number): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) return null;
  // JS Date 会把 2026-02-30 顺延成 3 月：换算后回代不一致就按未知日期处理。
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  date.setDate(date.getDate() + dayIndex);
  return date;
}

function weekdaysIn(text: string): number[] {
  const found = new Set<number>();
  const re = /(?:周|星期)([一二三四五六日天])(?:\s*(?:-|至|到)\s*(?:周|星期)?([一二三四五六日天]))?/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    const start = WEEKDAY_INDEX[match[1]];
    const end = match[2] ? WEEKDAY_INDEX[match[2]] : start;
    if (!start || !end) continue;
    if (start <= end) {
      for (let day = start; day <= end; day += 1) found.add(day);
    } else {
      for (let day = start; day <= 7; day += 1) found.add(day);
      for (let day = 1; day <= end; day += 1) found.add(day);
    }
  }
  return [...found].sort((a, b) => a - b);
}

/**
 * 从高德 opentime 解析“哪些星期开放”。
 * 只接受明确写了星期与营业时段的文本；解析不了就返回 null，宁可少提示也不误报。
 */
export function parseOpenDays(opentime: string): Set<number> | null {
  if (!opentime?.trim()) return null;
  const text = opentime.replace(/[–—−~～]/g, "-").replace(/\s+/g, " ").trim();
  const segments = text.split(/[；;。]/).map(segment => segment.trim()).filter(Boolean);
  if (!segments.length) return null;
  const open = new Set<number>();
  const closed = new Set<number>();
  let sawHours = false;

  for (const segment of segments) {
    const days = weekdaysIn(segment);
    const hasHours = /\d{1,2}:\d{2}\s*(?:-|至|到)\s*\d{1,2}:\d{2}/.test(segment) || /全天开放|24\s*小时/.test(segment);
    const closedWord = /关闭|闭馆|休息|不开放/.test(segment);
    if (days.length) {
      if (closedWord) {
        for (const day of days) closed.add(day);
      } else if (hasHours) {
        sawHours = true;
        for (const day of days) open.add(day);
      }
    } else if (!closedWord && /全天开放|24\s*小时/.test(segment)) {
      sawHours = true;
      for (const day of ALL_DAYS) open.add(day);
    }
  }

  if (!sawHours) return null;
  for (const day of closed) open.delete(day);
  return open.size ? new Set([...open].sort((a, b) => a - b)) : null;
}

function placeKey(place: Place): string {
  return place.id || place.name;
}

function openingDays(place: Place): Set<number> | null {
  if (place.unavailable) return null;
  if (place.verification?.status === "needs_check" || place.verification?.status === "unavailable") return null;
  return parseOpenDays(place.opentime ?? "");
}

/**
 * 行程体检 v1 只做“高置信、可解释”的检查：
 * 出发日期与固定闭馆日冲突、单日强度过高、相邻地点直线距离过远、同一地点重复出现。
 * 不做基于模型或猜测的用餐/兴趣判断，避免用假阳性打扰用户。
 */
export function runItineraryChecks(input: TripHealthInput): ItineraryCheck[] {
  const checks: ItineraryCheck[] = [];
  const days = Array.isArray(input.days) ? input.days : [];
  const backlog = Array.isArray(input.backlog) ? input.backlog : [];
  const startDate = input.request?.start_date ?? null;
  const weekly = new Map<string, { name: string; closedDays: number[] }>();
  // 只看是否真正解析出日期：start_date 非空但写坏时不能因此丢掉固定闭馆日提示。
  let hasDate = false;

  days.forEach((day, index) => {
    const date = startDateForDay(startDate, index);
    if (date) hasDate = true;
    for (const stop of day.stops ?? []) {
      const place = stop.place;
      if (!place) continue;
      const open = openingDays(place);
      if (!open || open.size === 0) continue;
      if (date) {
        const weekday = weekdayMon(date);
        if (!open.has(weekday)) {
          checks.push({ code: "closed_day", severity: "warning", day: index + 1, place: place.name, weekday });
        }
      } else if (open.size < 7) {
        const key = placeKey(place);
        const closedDays = ALL_DAYS.filter(dayOfWeek => !open.has(dayOfWeek));
        const existing = weekly.get(key);
        weekly.set(key, {
          name: place.name,
          closedDays: [...new Set([...(existing?.closedDays ?? []), ...closedDays])].sort((a, b) => a - b),
        });
      }
    }

    const minutes = (day.stops ?? []).reduce((sum, stop) => sum + (Number(stop.duration) || 0), 0);
    if ((day.stops?.length ?? 0) >= 7 || minutes >= 600) {
      checks.push({
        code: "heavy_day",
        severity: "warning",
        day: index + 1,
        stops: day.stops?.length ?? 0,
        minutes,
      });
    }

    let worst: { from: string; to: string; km: number } | null = null;
    const stops = day.stops ?? [];
    for (let i = 0; i + 1 < stops.length; i += 1) {
      const from = stops[i]?.place;
      const to = stops[i + 1]?.place;
      if (!from || !to) continue;
      const km = distanceKmBetween(from.location, to.location);
      if (km === null) continue;
      if (!worst || km > worst.km) worst = { from: from.name, to: to.name, km };
    }
    if (worst && worst.km >= 30) {
      checks.push({
        code: "long_hop",
        severity: "warning",
        day: index + 1,
        from: worst.from,
        to: worst.to,
        km: Math.round(worst.km * 10) / 10,
      });
    }
  });

  if (!hasDate && weekly.size > 0) {
    checks.push({ code: "weekly_closure", severity: "info", places: [...weekly.values()] });
  }

  const counts = new Map<string, { name: string; count: number }>();
  for (const stop of [...days.flatMap(day => day.stops ?? []), ...backlog]) {
    const place = stop?.place;
    if (!place) continue;
    const key = placeKey(place);
    if (!key) continue;
    const existing = counts.get(key);
    counts.set(key, { name: place.name, count: (existing?.count ?? 0) + 1 });
  }
  for (const item of counts.values()) {
    if (item.count > 1) {
      checks.push({ code: "duplicate_place", severity: "info", name: item.name, count: item.count });
    }
  }

  const rank: Record<ItineraryCheck["severity"], number> = { warning: 0, info: 1 };
  checks.sort((a, b) => {
    const dayA = "day" in a ? a.day : 99;
    const dayB = "day" in b ? b.day : 99;
    return rank[a.severity] - rank[b.severity] || dayA - dayB || a.code.localeCompare(b.code);
  });
  return checks;
}

export type HealthCopy = {
  sectionTitle: string;
  ariaLabel: string;
  count: (count: number) => string;
  weekday: (weekday: number) => string;
  closedDayTitle: (day: number) => string;
  closedDayDetail: (place: string, weekday: string) => string;
  weeklyTitle: (count: number) => string;
  weeklyItem: (name: string, weekdays: string) => string;
  weeklyDetail: (items: string[], remaining: number) => string;
  longHopTitle: (day: number) => string;
  longHopDetail: (from: string, to: string, km: string) => string;
  heavyTitle: (day: number) => string;
  heavyDetail: (stops: number, hours: string) => string;
  duplicateTitle: string;
  duplicateDetail: (name: string, count: number) => string;
};

const WEEKDAY_NAMES: Record<HealthLang, string[]> = {
  zh: ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"],
  en: ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
};

const COPY: Record<HealthLang, HealthCopy> = {
  zh: {
    sectionTitle: "行程体检",
    ariaLabel: "行程体检建议",
    count: (count) => count + " 项建议",
    weekday: (weekday) => WEEKDAY_NAMES.zh[weekday] ?? "",
    closedDayTitle: (day) => "第 " + day + " 天可能闭馆",
    closedDayDetail: (place, weekday) => place + " 在" + weekday + "闭馆，建议调整日期或替换地点。",
    weeklyTitle: (count) => count + " 个地点有固定闭馆日",
    weeklyItem: (name, weekdays) => name + " · " + weekdays + "闭馆",
    weeklyDetail: (items, remaining) => items.join("、") + (remaining ? " 等 " + remaining + " 个" : "") + "；选定出发日期后会自动核对。",
    longHopTitle: (day) => "第 " + day + " 天有一段较远的路程",
    longHopDetail: (from, to, km) => from + " → " + to + " 直线约 " + km + " 公里，建议确认交通方式与时间。",
    heavyTitle: (day) => "第 " + day + " 天安排偏满",
    heavyDetail: (stops, hours) => "共 " + stops + " 个地点，停留约 " + hours + " 小时，建议留出机动和用餐时间。",
    duplicateTitle: "同一地点重复安排",
    duplicateDetail: (name, count) => name + " 在行程中出现 " + count + " 次，确认是否需要合并。",
  },
  en: {
    sectionTitle: "Itinerary check",
    ariaLabel: "Itinerary check suggestions",
    count: (count) => count + " " + (count === 1 ? "check" : "checks"),
    weekday: (weekday) => WEEKDAY_NAMES.en[weekday] ?? "",
    closedDayTitle: (day) => "Day " + day + " may be closed",
    closedDayDetail: (place, weekday) => place + " is closed on " + weekday + ". Adjust the date or swap the stop.",
    weeklyTitle: (count) => count + " " + (count === 1 ? "place has" : "places have") + " fixed closing days",
    weeklyItem: (name, weekdays) => name + " · closed " + weekdays,
    weeklyDetail: (items, remaining) => items.join(", ") + (remaining ? " and " + remaining + " more" : "") + ". Set a start date to check automatically.",
    longHopTitle: (day) => "Day " + day + " has a long transfer",
    longHopDetail: (from, to, km) => from + " → " + to + " is about " + km + " km straight-line. Confirm transport and timing.",
    heavyTitle: (day) => "Day " + day + " is packed",
    heavyDetail: (stops, hours) => stops + " stops and about " + hours + " hours of visiting. Leave room for meals and delays.",
    duplicateTitle: "Place appears more than once",
    duplicateDetail: (name, count) => name + " appears " + count + " times. Check whether to merge the visits.",
  },
};

export function healthCopy(lang: HealthLang = "zh"): HealthCopy {
  return COPY[lang];
}
