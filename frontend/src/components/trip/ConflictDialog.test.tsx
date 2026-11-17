import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PageActiveProvider } from '../../app/providers/PageActiveProvider';
import type { Day, Stop, Trip } from '../../types/trip';
import { ConflictDialog } from './ConflictDialog';

function stop(id: string): Stop {
  return {
    place: { id, name: id, address: '', location: '120.1,30.2', opentime: '', cost: '', source_time: '' },
    duration: 60,
    reason: '',
  };
}

function day(): Day {
  return { stops: [stop('a'), stop('b'), stop('c')], routes: [], start_time: '09:00' };
}

function trip(days: Day[]): Trip {
  return {
    id: 1,
    version: 2,
    request: { city: '杭州', days: days.length, start_date: null, travelers: 2, interests: '', pace: '适中', budget: '', must_visit: '', transport: 'transit' },
    days,
    created_at: '',
  };
}

const onMerge = vi.fn();

function renderDialog(local: Trip, latest: Trip) {
  return render(
    <PageActiveProvider active>
      <ConflictDialog
        open
        busy={false}
        local={local}
        latest={latest}
        onClose={() => {}}
        onLoadLatest={() => {}}
        onKeepMine={() => {}}
        onDiscard={() => {}}
        onMerge={onMerge}
      />
    </PageActiveProvider>,
  );
}

describe('ConflictDialog 逐项合并', () => {
  it('checks mergeable fields by default and merges them', () => {
    onMerge.mockClear();
    const latest = day();
    latest.start_time = '08:30';
    latest.stops = [stop('a'), { ...stop('b'), duration: 90 }, stop('c')];
    renderDialog(trip([day()]), trip([latest]));

    const duration = screen.getByLabelText('第 1 天 · b · 停留') as HTMLInputElement;
    expect(duration.checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '合并并保存' }));

    expect(onMerge).toHaveBeenCalledTimes(1);
    const merged = onMerge.mock.calls[0][0] as Day[];
    expect(merged[0].start_time).toBe('08:30');
    expect(merged[0].stops[1].duration).toBe(90);
  });

  it('keeps local values for fields the user unchecks', () => {
    onMerge.mockClear();
    const latest = day();
    latest.start_time = '08:30';
    latest.stops = [stop('a'), { ...stop('b'), duration: 90 }, stop('c')];
    renderDialog(trip([day()]), trip([latest]));

    fireEvent.click(screen.getByLabelText('第 1 天 · 出发时间'));
    fireEvent.click(screen.getByRole('button', { name: '合并并保存' }));

    const merged = onMerge.mock.calls[0][0] as Day[];
    expect(merged[0].start_time).toBe('09:00');
    expect(merged[0].stops[1].duration).toBe(90);
  });

  it('shows who saved the online version and when', () => {
    const latest = day();
    latest.start_time = '08:30';
    const online = trip([latest]);
    online.last_edited_by = 'bob';
    online.last_edited_at = '2026-11-07T06:32:00+00:00';
    renderDialog(trip([day()]), online);

    expect(screen.getByText(/bob 最近保存/)).toBeTruthy();
  });

  it('disables merging when the day count differs', () => {
    renderDialog(trip([day()]), trip([day(), day()]));
    const button = screen.getByRole('button', { name: '合并并保存' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText('天数不同')).toBeTruthy();
  });
});
