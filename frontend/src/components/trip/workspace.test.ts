import { describe, expect, it } from 'vitest';
import type { Day, Route, Stop } from '../../types/trip';
import {
  dayDateText,
  diffTripDays,
  diffTripFields,
  dayTabLabel,
  formatDistance,
  mergeTripDays,
  reorderDayStops,
  reorderStops,
  routeText,
  stopTitle,
} from './workspace';

function stop(id: string, name = id): Stop {
  return {
    place: {
      id,
      name,
      address: '地址',
      location: '120.1,30.2',
      opentime: '',
      cost: '',
      source_time: '',
    },
    duration: 60,
    reason: '',
  };
}

function day(): Day {
  return {
    stops: [stop('a'), stop('b'), stop('c')],
    routes: [
      { origin: 'a', destination: 'b', mode: 'transit', duration: 600, distance: 1200, polyline: [], source_time: '' },
      { origin: 'b', destination: 'c', mode: 'transit', duration: 300, distance: 400, polyline: [], source_time: '' },
    ],
    start_time: '09:00',
  };
}

describe('routeText', () => {
  it('formats mode, minutes and kilometres', () => {
    const route: Route = {
      origin: 'a',
      destination: 'b',
      mode: 'transit',
      duration: 1680,
      distance: 3200,
      polyline: [],
      source_time: '',
    };
    expect(routeText(route, 'transit')).toBe('公交 / 28 分钟 / 3.2 公里');
  });

  it('returns an empty string when there is no route', () => {
    expect(routeText(undefined, 'walking')).toBe('');
  });

  it('falls back to the trip transport when a route has no mode', () => {
    expect(routeText({ origin: 'a', destination: 'b', mode: '', duration: 60, distance: 80, polyline: [], source_time: '' }, 'walking')).toBe('步行 / 1 分钟 / 80 米');
  });

  it('formats metre distances and rejects negative values', () => {
    expect(formatDistance(320)).toBe('320 米');
    expect(formatDistance(3200)).toBe('3.2 公里');
    expect(formatDistance(-1)).toBeNull();
  });
});

describe('reorder', () => {
  it('moves a stop without mutating the input', () => {
    const input = [stop('a'), stop('b'), stop('c')];
    const output = reorderStops(input, 0, 2);
    expect(output.map(item => item.place.id)).toEqual(['b', 'c', 'a']);
    expect(input.map(item => item.place.id)).toEqual(['a', 'b', 'c']);
  });

  it('ignores out-of-range indexes', () => {
    const input = [stop('a')];
    expect(reorderStops(input, 0, 3).map(item => item.place.id)).toEqual(['a']);
    expect(reorderStops(input, -1, 0).map(item => item.place.id)).toEqual(['a']);
  });

  it('clears stale routes when the day order changes', () => {
    const next = reorderDayStops(day(), 2, 0);
    expect(next.stops.map(item => item.place.id)).toEqual(['c', 'a', 'b']);
    expect(next.routes).toEqual([]);
  });
});

describe('day labels', () => {
  it('adds the calendar date when the trip has a start date', () => {
    expect(dayDateText(2, '2026-09-12')).toBe('9.14');
    expect(dayTabLabel(0, '2026-09-12')).toBe('第 1 天 · 9.12');
    expect(dayTabLabel(1, null)).toBe('第 2 天');
  });

  it('prefers the activity name over the place name', () => {
    expect(stopTitle({ ...stop('a', '西湖'), activity: '清晨散步' })).toBe('清晨散步');
    expect(stopTitle(stop('a', '西湖'))).toBe('西湖');
  });
});
describe('diffTripDays', () => {
  it('returns no items for identical days', () => {
    expect(diffTripDays([day()], [day()])).toEqual([]);
  });

  it('describes added stops and day count changes', () => {
    const more = { ...day(), stops: [stop('a'), stop('b'), stop('c'), stop('d')] };
    expect(diffTripDays([day()], [more])[0].text).toBe('第 1 天 · 地点 3 → 4 个');
    expect(diffTripDays([day()], [])[0].text).toContain('天数');
  });

  it('describes reordered stops without calling them added', () => {
    const reordered = { ...day(), stops: [stop('b'), stop('a'), stop('c')] };
    expect(diffTripDays([day()], [reordered])[0].text).toBe('第 1 天 · 地点顺序不同');
  });

  it('describes duration and start time changes', () => {
    const changed = day();
    changed.stops = [stop('a'), { ...stop('b'), duration: 90 }, stop('c')];
    changed.start_time = '08:30';
    expect(diffTripDays([day()], [changed])[0].text).toBe('第 1 天 · 停留或固定时间有调整，出发时间有调整');
  });
});

describe('diffTripFields', () => {
  it('splits same-order changes into mergeable fields', () => {
    const latest = day();
    latest.start_time = '08:30';
    latest.end_time = '18:00';
    latest.stops = [stop('a'), { ...stop('b'), duration: 90, fixed_time: '14:00' }, stop('c')];
    const diffs = diffTripFields([day()], [latest]);
    expect(diffs.map(item => item.label)).toEqual([
      '第 1 天 · 出发时间',
      '第 1 天 · 结束时间',
      '第 1 天 · b · 停留',
      '第 1 天 · b · 固定时间',
    ]);
    expect(diffs.every(item => item.merge !== null)).toBe(true);
    expect(diffs[0]).toMatchObject({ local: '09:00', latest: '08:30', merge: 'start_time', dayIndex: 0 });
    expect(diffs[2]).toMatchObject({ local: '60 分钟', latest: '90 分钟', stopId: 'b', merge: 'duration' });
  });

  it('marks reordered days as a whole-day replacement', () => {
    const latest = { ...day(), stops: [stop('b'), stop('a'), stop('c')], routes: [] };
    const diffs = diffTripFields([day()], [latest]);
    expect(diffs).toHaveLength(1);
    expect(diffs[0]).toMatchObject({ merge: 'day', dayIndex: 0 });
    expect(diffs[0].local).toBe('a → b → c');
    expect(diffs[0].latest).toBe('b → a → c');
  });

  it('refuses to merge when the day count differs', () => {
    const diffs = diffTripFields([day()], [day(), day()]);
    expect(diffs).toHaveLength(1);
    expect(diffs[0].merge).toBeNull();
    expect(diffs[0].label).toBe('天数不同');
  });
});

describe('mergeTripDays', () => {
  it('applies only the selected fields and keeps local values otherwise', () => {
    const local = [day()];
    const latest = day();
    latest.start_time = '08:30';
    latest.stops = [stop('a'), { ...stop('b'), duration: 90, fixed_time: '14:00' }, stop('c')];
    const merged = mergeTripDays(local, [latest], ['d0-duration-b']);
    expect(merged[0].start_time).toBe('09:00');
    expect(merged[0].stops[1].duration).toBe(90);
    expect(merged[0].stops[1].fixed_time).toBeUndefined();
    expect(local[0].stops[1].duration).toBe(60);
  });

  it('adopts a whole day when its plan changed', () => {
    const local = [day()];
    const latest = { ...day(), stops: [stop('b'), stop('a'), stop('c')], routes: [] };
    const merged = mergeTripDays(local, [latest], ['d0-plan']);
    expect(merged[0].stops.map(item => item.place.id)).toEqual(['b', 'a', 'c']);
    expect(merged[0].routes).toEqual([]);
    expect(local[0].stops.map(item => item.place.id)).toEqual(['a', 'b', 'c']);
  });
});

