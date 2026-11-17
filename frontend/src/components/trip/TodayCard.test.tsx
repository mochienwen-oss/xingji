import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Day, Place } from '../../types/trip';
import { TodayCard } from './TodayCard';

function place(id: string, name: string): Place {
  return { id, name, address: '', location: '120.121358,30.222692', opentime: '', cost: '', source_time: '' };
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

const scheduled = [
  { arrival: 540, start: 540, departure: 660 },
  { arrival: 690, start: 690, departure: 780 },
];

describe('TodayCard', () => {
  it('shows the next stop and an Amap navigation link', () => {
    render(
      <TodayCard
        day={day()}
        dayIndex={0}
        scheduled={scheduled}
        transport="transit"
        active
        now={new Date(2026, 10, 7, 10, 0)}
        onSelect={vi.fn()}
        onAddPlace={vi.fn()}
      />,
    );
    expect(screen.getByText('今天 · 第 1 天')).toBeInTheDocument();
    expect(screen.getByText('下一站')).toBeInTheDocument();
    expect(screen.getByText('灵隐寺')).toBeInTheDocument();
    expect(screen.getByText('预计 11:30 到')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: '导航到灵隐寺' });
    expect(link).toHaveAttribute('href', expect.stringContaining('uri.amap.com/navigation'));
    expect(link).toHaveAttribute('href', expect.stringContaining('mode=bus'));
  });

  it('offers adding a place and jumping to today', () => {
    const onAddPlace = vi.fn();
    const onSelect = vi.fn();
    render(
      <TodayCard
        day={day()}
        dayIndex={1}
        scheduled={scheduled}
        transport="walking"
        active={false}
        now={new Date(2026, 10, 7, 10, 0)}
        onSelect={onSelect}
        onAddPlace={onAddPlace}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '加地点' }));
    fireEvent.click(screen.getByRole('button', { name: '看今天' }));
    expect(onAddPlace).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('reports the end of the day after the last stop', () => {
    render(
      <TodayCard
        day={day()}
        dayIndex={0}
        scheduled={[{ arrival: 540, start: 540, departure: 600 }]}
        transport="transit"
        active
        now={new Date(2026, 10, 7, 19, 0)}
        onSelect={vi.fn()}
        onAddPlace={vi.fn()}
      />,
    );
    expect(screen.getByText('今天的安排已结束')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('handles a day without stops', () => {
    render(
      <TodayCard
        day={{ stops: [], routes: [] }}
        dayIndex={2}
        scheduled={[]}
        transport="transit"
        active
        now={new Date(2026, 10, 7, 10, 0)}
        onSelect={vi.fn()}
        onAddPlace={vi.fn()}
      />,
    );
    expect(screen.getByText('今天还没有安排地点')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '加地点' })).toBeInTheDocument();
  });
});
