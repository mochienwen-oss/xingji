import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OfflineToday } from './OfflineToday';
import type { CachedToday } from '../../lib/todayCache';

const cache: CachedToday = {
  v: 1,
  tripId: 7,
  title: '杭州两日',
  city: '杭州',
  startDate: '2026-11-07',
  dayIndex: 0,
  transport: 'transit',
  savedAt: '2026-11-07T10:00:00.000Z',
  stops: [
    {
      name: '西湖',
      address: '西湖地址',
      time: '09:00',
      duration: 120,
      navigationUrl: 'https://uri.amap.com/navigation?to=120.15,30.25,%E8%A5%BF%E6%B9%96',
    },
    { name: '灵隐寺', address: '', time: null, duration: 90, navigationUrl: null },
  ],
};

describe('OfflineToday', () => {
  it('shows the cached day and lets the user navigate', () => {
    render(<OfflineToday cache={cache} retrying={false} onRetry={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: '杭州两日' })).toBeInTheDocument();
    expect(screen.getByText('杭州 · 第 1 天 · 2 个地点')).toBeInTheDocument();
    expect(screen.getByText(/当前离线/)).toBeInTheDocument();
    expect(screen.getByText('西湖')).toBeInTheDocument();
    expect(screen.getByText(/时间待定/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '导航到西湖' })).toHaveAttribute('href', cache.stops[0].navigationUrl);
    expect(screen.queryByRole('link', { name: '导航到灵隐寺' })).toBeNull();
  });

  it('retries the connection and can go back', () => {
    const onRetry = vi.fn();
    const onBack = vi.fn();
    render(<OfflineToday cache={cache} retrying={false} onRetry={onRetry} onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: '重新连接' }));
    fireEvent.click(screen.getByRole('button', { name: '返回我的行程' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('handles a cached day without stops', () => {
    render(<OfflineToday cache={{ ...cache, stops: [] }} retrying onRetry={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText('缓存的这一天还没有地点。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '正在重连…' })).toBeDisabled();
  });
});
