import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../lib/api';
import { SessionProvider } from '../app/providers/SessionProvider';
import { ToastProvider } from '../app/providers/ToastProvider';
import type { SharedTripSummary } from '../types/trip';
import { CollabPage } from './CollabPage';

const mocked = vi.hoisted(() => ({ api: vi.fn(), me: vi.fn() }));

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return { ...actual, api: mocked.api, me: mocked.me };
});

const SESSION = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
  accepted_terms_at: null,
};

type Call = { url: string; method: string };

const TRIPS: SharedTripSummary[] = [
  {
    id: 7,
    title: '杭州周末',
    city: '杭州',
    role: 'edit',
    owner: 'bob',
    member_count: 3,
    online: 2,
    is_owner: false,
    is_public: false,
  },
  {
    id: 8,
    title: null,
    city: '苏州',
    role: 'read',
    owner: 'carol',
    member_count: 2,
    online: 0,
    is_owner: false,
    is_public: false,
  },
];

/** 记录请求并按 url 分发，默认只认识 GET /trips/shared。 */
function mockApi(handler?: (url: string, method: string) => unknown) {
  const calls: Call[] = [];
  mocked.api.mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    calls.push({ url, method });
    if (handler) return handler(url, method);
    if (url === '/trips/shared') return { trips: TRIPS };
    throw new Error('unexpected request ' + method + ' ' + url);
  });
  return calls;
}

function renderPage() {
  return render(
    <SessionProvider>
      <ToastProvider>
        <CollabPage />
      </ToastProvider>
    </SessionProvider>,
  );
}

describe('CollabPage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    history.replaceState(null, '', '#/collab');
    mocked.api.mockReset();
    mocked.me.mockReset();
    mocked.me.mockResolvedValue(SESSION);
  });

  it('lists only shared trips with owner, member count and online presence', async () => {
    const calls = mockApi();
    renderPage();

    expect(await screen.findByText('杭州周末')).toBeInTheDocument();
    expect(screen.getByText('杭州 · @bob 创建 · 共 3 人协作')).toBeInTheDocument();
    expect(screen.getByText('苏州 · @carol 创建 · 共 2 人协作')).toBeInTheDocument();
    // 没起名字的行程用城市兜底，和「我的行程」保持一致。
    expect(screen.getByText('苏州旅行计划')).toBeInTheDocument();
    expect(screen.getByText('2 人在线')).toBeInTheDocument();
    expect(screen.queryByText('0 人在线')).toBeNull();
    expect(screen.getByText('可编辑')).toBeInTheDocument();
    expect(screen.getByText('只读')).toBeInTheDocument();
    expect(calls.filter(call => call.url === '/trips/shared')).toHaveLength(1);
  });

  it('hides trips the user owns so 协同 stays separate from 我的行程', async () => {
    mockApi(() => ({
      trips: [
        ...TRIPS,
        { id: 9, title: '自己的公开行程', city: '成都', role: 'owner', owner: 'alice', is_owner: true },
      ],
    }));
    renderPage();

    expect(await screen.findByText('杭州周末')).toBeInTheDocument();
    expect(screen.queryByText('自己的公开行程')).toBeNull();
  });

  it('leaves a collab trip after confirmation and refreshes the list', async () => {
    let trips = [...TRIPS];
    const calls = mockApi((url, method) => {
      if (url === '/trips/shared') return { trips };
      if (url === '/trips/7/members/me' && method === 'DELETE') {
        trips = trips.filter(item => item.id !== 7);
        return { ok: true };
      }
      throw new Error('unexpected request ' + method + ' ' + url);
    });
    renderPage();

    await screen.findByText('杭州周末');
    fireEvent.click(screen.getAllByRole('button', { name: '退出协作' })[0]);

    const dialog = await screen.findByRole('dialog', { name: '退出这份协作行程？' });
    fireEvent.click(within(dialog).getByRole('button', { name: '退出协作' }));

    expect(await screen.findByText('已退出协作。')).toBeInTheDocument();
    expect(calls).toContainEqual({ url: '/trips/7/members/me', method: 'DELETE' });
    await waitFor(() => expect(screen.queryByText('杭州周末')).toBeNull());
    // 刷新后只剩另一份协作行程。
    expect(screen.getByText('苏州旅行计划')).toBeInTheDocument();
  });

  it('does not leave when the confirmation is cancelled', async () => {
    const calls = mockApi();
    renderPage();

    await screen.findByText('杭州周末');
    fireEvent.click(screen.getAllByRole('button', { name: '退出协作' })[0]);
    const dialog = await screen.findByRole('dialog', { name: '退出这份协作行程？' });
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(calls.filter(call => call.method === 'DELETE')).toHaveLength(0);
    expect(screen.getByText('杭州周末')).toBeInTheDocument();
  });

  it('explains how to join when there is no collab trip yet', async () => {
    mockApi(() => ({ trips: [] }));
    renderPage();

    expect(await screen.findByText('还没有协作行程')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '去行程页输入分享码' }));
    expect(window.location.hash).toBe('#/trips');
  });

  it('asks guests to sign in without requesting shared trips', async () => {
    mocked.me.mockRejectedValue(new ApiError('请先登录', 401));
    const calls = mockApi();
    const authSpy = vi.fn();
    window.addEventListener('xingji:open-auth', authSpy);

    try {
      renderPage();
      expect(await screen.findByText('登录后查看协作行程')).toBeInTheDocument();
      expect(calls.filter(call => call.url === '/trips/shared')).toHaveLength(0);

      fireEvent.click(screen.getByRole('button', { name: '登录 / 注册' }));
      expect(authSpy).toHaveBeenCalledTimes(1);
      const event = authSpy.mock.calls[0][0] as CustomEvent<{ intent: string }>;
      expect(event.detail.intent).toBe('login');
    } finally {
      window.removeEventListener('xingji:open-auth', authSpy);
    }
  });

  it('retries after a failed first load', async () => {
    let attempt = 0;
    mockApi(() => {
      attempt += 1;
      if (attempt === 1) throw new Error('网络开小差了');
      return { trips: TRIPS };
    });
    renderPage();

    expect(await screen.findByText('协作行程暂时没有取到')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(await screen.findByText('杭州周末')).toBeInTheDocument();
    expect(attempt).toBe(2);
  });

  it('refreshes silently every 15 seconds and keeps the old list when a refresh fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const clearSpy = vi.spyOn(window, 'clearInterval');
    try {
      let attempt = 0;
      mockApi(() => {
        attempt += 1;
        if (attempt === 1) return { trips: TRIPS };
        throw new Error('刷新失败');
      });
      const view = renderPage();

      await vi.waitFor(() => expect(screen.getByText('杭州周末')).toBeInTheDocument());
      expect(attempt).toBe(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(attempt).toBe(2);
      // 静默刷新失败：保留旧列表，不闪错误。
      expect(screen.getByText('杭州周末')).toBeInTheDocument();
      expect(screen.queryByText('协作行程暂时没有取到')).toBeNull();

      view.unmount();
      expect(clearSpy).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
      clearSpy.mockRestore();
    }
  });
});
