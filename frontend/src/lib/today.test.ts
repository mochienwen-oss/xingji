import { describe, expect, it } from 'vitest';
import type { Day, Place } from '../types/trip';
import { minutesSinceMidnight, nextStopIndex, todayCardModel, todayIndex } from './today';

function place(id: string, name: string, location = '120.1,30.2'): Place {
  return { id, name, address: '', location, opentime: '', cost: '', source_time: '' };
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

describe('todayIndex', () => {
  it('returns the day index when today is inside the trip', () => {
    expect(todayIndex('2026-11-07', 3, new Date(2026, 10, 8, 10, 0))).toBe(1);
  });

  it('returns 0 on the first day and null outside the range', () => {
    expect(todayIndex('2026-11-07', 3, new Date(2026, 10, 7, 23, 30))).toBe(0);
    expect(todayIndex('2026-11-07', 3, new Date(2026, 10, 6, 10, 0))).toBeNull();
    expect(todayIndex('2026-11-07', 3, new Date(2026, 10, 10, 10, 0))).toBeNull();
  });

  it('ignores missing or malformed dates', () => {
    expect(todayIndex(null, 3)).toBeNull();
    expect(todayIndex('2026-11', 3)).toBeNull();
    expect(todayIndex('2026-11-07', 0)).toBeNull();
  });
});

describe('nextStopIndex', () => {
  it('returns the first stop before it starts', () => {
    expect(nextStopIndex([{ arrival: 540, start: 540, departure: 660 }, { arrival: 690, start: 690, departure: 780 }], 500)).toBe(0);
  });

  it('returns the following stop while the current one is ongoing', () => {
    expect(nextStopIndex([{ arrival: 540, start: 540, departure: 660 }, { arrival: 690, start: 690, departure: 780 }], 600)).toBe(1);
  });

  it('returns null after the last stop departs', () => {
    expect(nextStopIndex([{ arrival: 540, start: 540, departure: 660 }], 700)).toBeNull();
  });

  it('falls back to the first stop when route time is missing', () => {
    expect(nextStopIndex([{ arrival: null, start: 540, departure: null }], 700)).toBe(0);
  });
});

describe('todayCardModel', () => {
  it('picks the next stop and its arrival clock', () => {
    const scheduled = [
      { arrival: 540, start: 540, departure: 660 },
      { arrival: 690, start: 690, departure: 780 },
    ];
    const model = todayCardModel(day(), scheduled, new Date(2026, 10, 7, 10, 0));
    expect(model.stop?.place.name).toBe('灵隐寺');
    expect(model.start).toBe(690);
  });

  it('returns no stop after the itinerary ends', () => {
    const model = todayCardModel(day(), [{ arrival: 540, start: 540, departure: 600 }], new Date(2026, 10, 7, 19, 0));
    expect(model.stop).toBeNull();
  });
});

describe('minutesSinceMidnight', () => {
  it('converts local hours and minutes', () => {
    expect(minutesSinceMidnight(new Date(2026, 10, 7, 9, 35))).toBe(575);
  });
});
