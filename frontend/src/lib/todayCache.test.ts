import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Day, Place, Trip } from '../types/trip';
import {
  buildTodayCache,
  clearAllTodayCaches,
  readTodayCache,
  saveTodayCache,
} from './todayCache';

/** 缓存键前缀属于存储契约，测试直接固定，避免为了测试暴露生产常量。 */
const TODAY_KEY_PREFIX = 'xingji.today.v1.';

function place(id: string, name: string, location = '120.15,30.25'): Place {
  return { id, name, address: `${name}地址`, location, opentime: '', cost: '', source_time: '' };
}

function day(): Day {
  return {
    start_time: '09:00',
    end_time: '18:00',
    stops: [
      { place: place('a', '西湖'), duration: 120, reason: '' },
      { place: place('b', '灵隐寺'), duration: 90, reason: '' },
    ],
    routes: [],
  };
}

function trip(startDate: string | null = '2026-11-07'): Trip {
  return {
    id: 7,
    title: '杭州两日',
    request: {
      city: '杭州',
      days: 2,
      start_date: startDate,
      travelers: 2,
      interests: '',
      pace: '适中',
      budget: '',
      must_visit: '',
      transport: 'transit',
    },
    days: [day(), day()],
  };
}

const now = new Date(2026, 10, 7, 10, 0);

describe('todayCache', () => {
  beforeEach(() => localStorage.clear());

  it('builds a compact snapshot with times and navigation links', () => {
    const cache = buildTodayCache(trip(), 0, day(), now);
    expect(cache).not.toBeNull();
    expect(cache?.title).toBe('杭州两日');
    expect(cache?.stops.map(stop => stop.name)).toEqual(['西湖', '灵隐寺']);
    expect(cache?.stops[0].time).toBe('09:00');
    expect(cache?.stops[0].navigationUrl).toContain('uri.amap.com/navigation');
    expect(cache?.stops[0].navigationUrl).toContain('mode=bus');
  });

  it('writes and reads today only', () => {
    expect(saveTodayCache(trip(), 0, day(), now)).not.toBeNull();
    const read = readTodayCache(7, now);
    expect(read?.stops[1].name).toBe('灵隐寺');
    expect(readTodayCache(7, new Date(2026, 10, 8, 10, 0))).toBeNull();
  });

  it('does nothing without a start date', () => {
    expect(buildTodayCache(trip(null), 0, day(), now)).toBeNull();
    expect(saveTodayCache(trip(null), 0, day(), now)).toBeNull();
  });

  it('clears every cached trip when the session ends', () => {
    saveTodayCache(trip(), 0, day(), now);
    localStorage.setItem(TODAY_KEY_PREFIX + 8, '{}');
    clearAllTodayCaches();
    expect(Object.keys(localStorage).filter(key => key.startsWith(TODAY_KEY_PREFIX))).toHaveLength(0);
  });

  it('ignores malformed or over-long data', () => {
    localStorage.setItem(TODAY_KEY_PREFIX + 7, '{bad json');
    expect(readTodayCache(7, now)).toBeNull();

    const cache = buildTodayCache(trip(), 0, day(), now);
    localStorage.setItem(TODAY_KEY_PREFIX + 7, JSON.stringify({ ...cache, v: 2 }));
    expect(readTodayCache(7, now)).toBeNull();

    localStorage.setItem(TODAY_KEY_PREFIX + 7, JSON.stringify({ ...cache, stops: [{ name: '' }] }));
    expect(readTodayCache(7, now)).toBeNull();
  });

  it('degrades silently when storage rejects writes', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    expect(saveTodayCache(trip(), 0, day(), now)).toBeNull();
    spy.mockRestore();
  });
});
