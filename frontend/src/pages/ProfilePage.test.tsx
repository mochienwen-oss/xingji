import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { DraftProvider } from '../app/providers/DraftProvider';
import { SessionProvider } from '../app/providers/SessionProvider';
import { ToastProvider } from '../app/providers/ToastProvider';
import { TripListProvider } from '../app/providers/TripListProvider';
import { ApiError, type MeResponse } from '../lib/api';
import type { PlanRequest, TripSummary } from '../types/trip';
import { ProfilePage } from './ProfilePage';

const mocked = vi.hoisted(() => ({
  api: vi.fn(),
  me: vi.fn(),
  acceptTerms: vi.fn(),
  logout: vi.fn(),
}));

vi.mock('../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return {
    ...actual,
    api: mocked.api,
    me: mocked.me,
    acceptTerms: mocked.acceptTerms,
    logout: mocked.logout,
  };
});

const alice: MeResponse = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
  accepted_terms_at: '2026-01-01T00:00:00Z',
};

function requestFor(city: string): PlanRequest {
  return {
    city,
    days: 3,
    start_date: null,
    travelers: 2,
    interests: '',
    pace: '轻松',
    budget: '舒适',
    must_visit: '',
    transport: '公共交通',
  };
}

function trip(id: number, city: string, title: string | null): TripSummary {
  return { id, city, title, request: requestFor(city) };
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <DraftProvider>
        <TripListProvider>
          <ToastProvider>{children}</ToastProvider>
        </TripListProvider>
      </DraftProvider>
    </SessionProvider>
  );
}

const authSpy = vi.fn();

beforeEach(() => {
  vi.resetAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '#/profile');
  authSpy.mockClear();
  window.addEventListener('xingji:open-auth', authSpy);
  mocked.me.mockRejectedValue(new ApiError('未登录', 401));
  mocked.api.mockResolvedValue([]);
});

afterEach(() => {
  window.removeEventListener('xingji:open-auth', authSpy);
});

describe('ProfilePage', () => {
  it('游客能看到登录 CTA 与示例，点击后发出对应认证意图', async () => {
    const user = userEvent.setup();
    render(<Providers><ProfilePage /></Providers>);

    expect(await screen.findByText('游客模式')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '把旅程留在账号里' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '旅程示例' })).toBeInTheDocument();
    expect(screen.getByText(/示例 · 杭州三日/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '注册新账号' }));

    expect(authSpy).toHaveBeenCalledTimes(1);
    const event = authSpy.mock.calls[0]?.[0] as CustomEvent<{ intent?: string }>;
    expect(event.detail.intent).toBe('register');
  });

  it('登录用户看到旅程、城市与收藏地点三格统计，最近卡点击进入对应行程', async () => {
    const user = userEvent.setup();
    mocked.me.mockResolvedValue(alice);
    mocked.api.mockImplementation(async (url: string) =>
      url === '/trips'
        ? [
            trip(1, '京都', '京都慢行'),
            trip(2, '京都', '另一段京都'),
            trip(3, '大阪', '大阪两日'),
            trip(4, '东京', '东京周末'),
          ]
        : [],
    );
    window.localStorage.setItem(
      'xingji-draft:alice',
      JSON.stringify({ places: [{ id: 'p1', city: '京都' }, { id: 'p2', city: '大阪' }] }),
    );

    render(<Providers><ProfilePage /></Providers>);

    expect(await screen.findByText('最近旅程')).toBeInTheDocument();
    const stats = await screen.findByRole('list', { name: '旅行概况' });
    expect(within(stats).getAllByRole('listitem')).toHaveLength(3);
    await waitFor(() => expect(within(stats).getByText('4')).toBeInTheDocument());
    expect(within(stats).getByText('3')).toBeInTheDocument();
    await waitFor(() => expect(within(stats).getByText('2')).toBeInTheDocument());
    expect(within(stats).getByText('段旅程')).toBeInTheDocument();
    expect(within(stats).getByText('座城市')).toBeInTheDocument();
    expect(within(stats).getByText('个收藏地点')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: '打开东京周末' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '打开京都慢行' }));
    expect(window.location.hash).toBe('#/trips/1');
  });

  it('未绑定邮箱时给出绑定提示，并可进入账户设置', async () => {
    const user = userEvent.setup();
    mocked.me.mockResolvedValue({
      ...alice,
      email: null,
      email_verified: false,
      needs_email: true,
      accepted_terms_at: null,
    });

    render(<Providers><ProfilePage /></Providers>);

    expect(await screen.findByText('绑定邮箱，找回密码更方便')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '去绑定邮箱' }));
    expect(window.location.hash).toBe('#/settings/account');
  });

  it('条款更新时显示非阻断提示，同意后刷新账户状态', async () => {
    const user = userEvent.setup();
    mocked.me
      .mockResolvedValueOnce({ ...alice, needs_terms: true })
      .mockResolvedValue(alice);
    mocked.acceptTerms.mockResolvedValue({ accepted_terms_at: '2026-11-01T00:00:00Z' });

    render(<Providers><ProfilePage /></Providers>);

    expect(await screen.findByText('服务条款已更新')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '同意' }));

    await waitFor(() => expect(mocked.acceptTerms).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByText('服务条款已更新')).not.toBeInTheDocument(),
    );
    expect(await screen.findByText('已同意最新服务条款')).toBeInTheDocument();
  });
});
