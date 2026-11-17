import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TripsTab } from '../app/routing/routes';
import { SessionProvider } from '../app/providers/SessionProvider';
import { ToastProvider } from '../app/providers/ToastProvider';
import { TripListProvider } from '../app/providers/TripListProvider';
import { recoverDaysLeft } from '../components/trips/RecycleBin';
import { ApiError } from '../lib/api';
import { consumeForkDatePrompt } from '../lib/forkPrompt';
import type {
  DeletedTrip,
  PlanRequest,
  PlazaTrip,
  TripSummary,
} from '../types/trip';
import { TripsPage } from './TripsPage';

const mocked = vi.hoisted(() => ({ api: vi.fn(), me: vi.fn() }));

vi.mock('../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: mocked.api, me: mocked.me };
});

const DAY_MS = 86_400_000;
const SESSION = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
  accepted_terms_at: null,
};

type Call = { method: string; url: string; body?: string };

type Server = {
  trips: TripSummary[];
  deleted: DeletedTrip[];
  plaza: PlazaTrip[];
  forkId: number;
  join: { trip_id: number; title: string; already_member: boolean } | { error: ApiError };
  calls: Call[];
};

let server: Server;
const authSpy = vi.fn();

function recentIso(daysAgo: number): string {
  return new Date(Date.now() - daysAgo * DAY_MS).toISOString();
}

function requestFor(city: string, days: number, startDate: string | null): PlanRequest {
  return {
    city,
    days,
    start_date: startDate,
    travelers: 2,
    interests: '',
    pace: '轻松',
    budget: '舒适',
    must_visit: '',
    transport: '公共交通',
  };
}

function makeTrip(id: number, city: string, title: string | null, startDate: string | null): TripSummary {
  return { id, city, title, request: requestFor(city, 3, startDate) };
}

function renderPage(tab: TripsTab) {
  return render(
    <SessionProvider>
      <TripListProvider>
        <ToastProvider>
          <TripsPage tab={tab} />
        </ToastProvider>
      </TripListProvider>
    </SessionProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '#/trips');
  mocked.api.mockReset();
  mocked.me.mockReset();
  authSpy.mockClear();
  window.addEventListener('xingji:open-auth', authSpy);

  server = {
    trips: [],
    deleted: [],
    plaza: [],
    forkId: 99,
    join: { trip_id: 12, title: '京都漫步', already_member: false },
    calls: [],
  };
  mocked.me.mockResolvedValue(SESSION);

  mocked.api.mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    server.calls.push({ method, url, body: typeof init.body === 'string' ? init.body : undefined });

    if (method === 'GET' && url === '/trips') return server.trips;
    if (method === 'GET' && url === '/trips?deleted=true') return server.deleted;
    if (method === 'GET' && url === '/plaza') return { trips: server.plaza };

    const tripPath = /^\/trips\/(\d+)$/.exec(url);
    if (tripPath && method === 'PATCH') {
      const id = Number(tripPath[1]);
      const body = JSON.parse(String(init.body ?? '{}')) as { title?: string };
      server.trips = server.trips.map(trip =>
        trip.id === id ? { ...trip, title: body.title ?? null } : trip,
      );
      return { id, title: body.title };
    }
    if (tripPath && method === 'DELETE') {
      const id = Number(tripPath[1]);
      const target = server.trips.find(trip => trip.id === id);
      server.trips = server.trips.filter(trip => trip.id !== id);
      if (target) {
        server.deleted = [
          { id, city: target.city, title: target.title, deleted_at: new Date().toISOString() },
          ...server.deleted,
        ];
      }
      return { ok: true, deleted_at: new Date().toISOString(), purge_days: 7 };
    }

    const restorePath = /^\/trips\/(\d+)\/restore$/.exec(url);
    if (restorePath && method === 'POST') {
      const id = Number(restorePath[1]);
      const item = server.deleted.find(entry => entry.id === id);
      server.deleted = server.deleted.filter(entry => entry.id !== id);
      if (item) {
        server.trips = [makeTrip(item.id, item.city, item.title ?? null, null), ...server.trips];
      }
      return { ok: true, id };
    }

    const forkPath = /^\/plaza\/(\d+)\/fork$/.exec(url);
    if (forkPath && method === 'POST') {
      const created = makeTrip(server.forkId, '杭州', '西湖慢走（副本）', null);
      server.trips = [created, ...server.trips];
      return created;
    }

    if (method === 'POST' && url === '/trips/join') {
      if ('error' in server.join) throw server.join.error;
      return server.join;
    }

    throw new Error('未模拟的请求：' + method + ' ' + url);
  });
});

afterEach(() => {
  window.removeEventListener('xingji:open-auth', authSpy);
});

describe('TripsPage', () => {
  it('渲染我的行程标题、分段和卡片，切换分段改写 hash', async () => {
    server.trips = [makeTrip(2, '杭州', '杭州三日', '2026-11-05'), makeTrip(1, '泉州', null, null)];
    server.deleted = [{ id: 5, city: '苏州', title: '苏州两日', deleted_at: recentIso(2) }];
    renderPage('mine');

    expect(screen.getByRole('heading', { level: 1, name: '我的行程' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '我的' })).toHaveAttribute('aria-selected', 'true');
    await screen.findByRole('heading', { level: 2, name: '杭州三日' });
    expect(screen.getByRole('heading', { level: 2, name: '泉州旅行计划' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /回收站/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: '广场' }));
    expect(window.location.hash).toBe('#/trips?tab=plaza');
  });

  it('空态：从地图开始与示例城市都去探索页', async () => {
    renderPage('mine');

    await screen.findByRole('heading', { level: 2, name: '还没有行程' });
    fireEvent.click(screen.getByRole('button', { name: '从地图开始' }));
    expect(window.location.hash).toBe('#/explore');

    window.history.replaceState(null, '', '#/trips');
    fireEvent.click(screen.getByRole('button', { name: '泉州' }));
    expect(window.location.hash).toBe('#/explore');
  });

  it('筛选 chips：有日期 / 待定 只显示对应行程', async () => {
    server.trips = [
      makeTrip(2, '杭州', '杭州三日', '2026-11-05'),
      makeTrip(1, '泉州', null, null),
    ];
    renderPage('mine');

    await screen.findByRole('heading', { level: 2, name: '杭州三日' });
    await screen.findByRole('heading', { level: 2, name: '泉州旅行计划' });

    fireEvent.click(screen.getByRole('button', { name: '有日期' }));
    expect(screen.getByRole('heading', { level: 2, name: '杭州三日' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: '泉州旅行计划' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '待定' }));
    expect(screen.getByRole('heading', { level: 2, name: '泉州旅行计划' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: '杭州三日' })).not.toBeInTheDocument();
  });

  it('recoverDaysLeft 按 deleted_at + 7 天算剩余天数', () => {
    const now = Date.parse('2026-11-03T00:00:00.000Z');
    expect(recoverDaysLeft('2026-11-01T00:00:00.000Z', now)).toBe(5);
    expect(recoverDaysLeft('2026-10-01T00:00:00.000Z', now)).toBe(0);
    expect(recoverDaysLeft('不是日期', now)).toBe(0);
  });

  it('删除需要确认，确认后调用 DELETE 并刷新列表', async () => {
    server.trips = [makeTrip(2, '杭州', '杭州三日', '2026-11-05')];
    renderPage('mine');

    await screen.findByRole('heading', { level: 2, name: '杭州三日' });
    fireEvent.click(screen.getByRole('button', { name: '更多操作：杭州三日' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '删除' }));

    const dialog = await screen.findByRole('dialog', { name: '删除这段行程？' });
    expect(within(dialog).getByText(/7 天内可以在回收站恢复/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(server.calls.some(call => call.method === 'DELETE' && call.url === '/trips/2')).toBe(true);
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => {
      expect(screen.queryByRole('heading', { level: 2, name: '杭州三日' })).not.toBeInTheDocument();
    });
    expect(await screen.findByText('已移到回收站，7 天内可以恢复。')).toBeInTheDocument();
  });

  it('删除确认：行程有协作者时提示会影响 N 位协作者', async () => {
    server.trips = [{ ...makeTrip(7, '杭州', '杭州三日', '2026-11-05'), collaborator_count: 2 }];
    renderPage('mine');

    await screen.findByRole('heading', { level: 2, name: '杭州三日' });
    fireEvent.click(screen.getByRole('button', { name: '更多操作：杭州三日' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '删除' }));

    const dialog = await screen.findByRole('dialog', { name: '删除这段行程？' });
    expect(
      within(dialog).getByText(
        '删除后 7 天内可以在回收站恢复。这份行程有 2 位协作者，删除后他们会同时失去访问。',
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(server.calls.some(call => call.method === 'DELETE' && call.url === '/trips/7')).toBe(true);
    });
  });

  it('回收站显示剩余天数并调用 restore', async () => {
    server.deleted = [{ id: 3, city: '苏州', title: '苏州两日', deleted_at: recentIso(2) }];
    renderPage('mine');

    const trigger = await screen.findByRole('button', { name: /回收站/ });
    fireEvent.click(trigger);

    const dialog = await screen.findByRole('dialog', { name: '回收站' });
    expect(within(dialog).getByText(/还有 5 天可恢复/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '恢复' }));

    await waitFor(() => {
      expect(server.calls.some(call => call.method === 'POST' && call.url === '/trips/3/restore')).toBe(true);
    });
    await waitFor(() => expect(within(dialog).queryByText('苏州两日')).not.toBeInTheDocument());
    expect(await screen.findByText('已恢复到我的行程。')).toBeInTheDocument();
  });

  it('广场游客也直接拉取并展示公开行程，复制时才要求登录', async () => {
    mocked.me.mockRejectedValue(new ApiError('登录已过期，请重新登录', 401));
    server.plaza = [{ id: 11, title: '西湖慢走', city: '杭州', days: 2, owner: 'bob', start_date: null }];
    renderPage('plaza');

    await screen.findByRole('heading', { level: 2, name: '西湖慢走' });
    expect(server.calls.some(call => call.url === '/plaza')).toBe(true);
    expect(screen.queryByRole('heading', { level: 2, name: '登录后逛广场' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '西湖慢走' }));
    expect(authSpy).toHaveBeenCalledTimes(1);
    const event = authSpy.mock.calls[0][0] as CustomEvent<{ intent: string }>;
    expect(event.detail.intent).toBe('login');
    expect(server.calls.some(call => call.method === 'POST' && call.url === '/plaza/11/fork')).toBe(false);
  });

  it('广场确认 fork 后刷新我的列表并跳到新行程', async () => {
    server.plaza = [{ id: 11, title: '西湖慢走', city: '杭州', days: 2, owner: 'bob', start_date: null }];
    renderPage('plaza');

    await screen.findByRole('heading', { level: 2, name: '西湖慢走' });
    const tripListCalls = () => server.calls.filter(call => call.method === 'GET' && call.url === '/trips').length;
    await waitFor(() => expect(tripListCalls()).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: '西湖慢走' }));
    const dialog = await screen.findByRole('dialog', { name: '复制到我的行程？' });
    expect(within(dialog).getByText(/不复制原作者的对话/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '复制一份' }));

    await waitFor(() => {
      expect(server.calls.some(call => call.method === 'POST' && call.url === '/plaza/11/fork')).toBe(true);
    });
    await waitFor(() => expect(tripListCalls()).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(window.location.hash).toBe('#/trips/99'));
    expect(await screen.findByText('已复制到我的行程。')).toBeInTheDocument();
    // 公开副本不含具体日期，落地页需要弹出发日期引导。
    expect(consumeForkDatePrompt(99)).toBe(true);
  });

  it('输入分享码加入：打开弹窗、自动大写、不足 8 位禁用', async () => {
    server.trips = [makeTrip(1, '杭州', '杭州三日', '2026-11-05')];
    renderPage('mine');
    await screen.findByRole('heading', { level: 2, name: '杭州三日' });

    fireEvent.click(screen.getByRole('button', { name: '输入分享码加入' }));
    const dialog = await screen.findByRole('dialog', { name: '加入协作行程' });
    expect(within(dialog).getByText('输入朋友给你的 8 位分享码')).toBeInTheDocument();

    const input = within(dialog).getByLabelText('分享码');
    fireEvent.change(input, { target: { value: 'ab3-d5f7h' } });
    expect(input).toHaveValue('AB3D5F7H');
    expect(within(dialog).getByRole('button', { name: '加入' })).toBeEnabled();

    fireEvent.change(input, { target: { value: 'AB3D5F7' } });
    expect(within(dialog).getByRole('button', { name: '加入' })).toBeDisabled();
  });

  it('输入分享码加入：成功后关闭弹窗、刷新列表并跳转', async () => {
    server.trips = [makeTrip(1, '杭州', '杭州三日', '2026-11-05')];
    renderPage('mine');
    await screen.findByRole('heading', { level: 2, name: '杭州三日' });
    const tripListCalls = () =>
      server.calls.filter(call => call.method === 'GET' && call.url === '/trips').length;
    await waitFor(() => expect(tripListCalls()).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: '输入分享码加入' }));
    const dialog = await screen.findByRole('dialog', { name: '加入协作行程' });
    fireEvent.change(within(dialog).getByLabelText('分享码'), { target: { value: 'ab3d5f7h' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '加入' }));

    await waitFor(() => {
      expect(
        server.calls.some(
          call =>
            call.method === 'POST' &&
            call.url === '/trips/join' &&
            call.body === JSON.stringify({ code: 'AB3D5F7H' }),
        ),
      ).toBe(true);
    });
    await waitFor(() => expect(window.location.hash).toBe('#/trips/12'));
    await waitFor(() => expect(tripListCalls()).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText('已加入「京都漫步」')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '加入协作行程' })).not.toBeInTheDocument(),
    );
  });

  it('输入分享码加入：404 显示固定文案，弹窗留在原地', async () => {
    server.join = { error: new ApiError('Not Found', 404) };
    renderPage('mine');
    await screen.findByRole('heading', { level: 2, name: '还没有行程' });

    fireEvent.click(screen.getByRole('button', { name: '输入分享码加入' }));
    const dialog = await screen.findByRole('dialog', { name: '加入协作行程' });
    fireEvent.change(within(dialog).getByLabelText('分享码'), { target: { value: 'AB3D5F7H' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '加入' }));

    expect(await screen.findByText('分享码无效或已停用，请向朋友确认。')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '加入协作行程' })).toBeInTheDocument();
    expect(window.location.hash).toBe('#/trips');
  });
});
