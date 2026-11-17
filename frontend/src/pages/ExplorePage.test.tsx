import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../lib/api';
import type { Place, Trip } from '../types/trip';
import { DraftProvider } from '../app/providers/DraftProvider';
import { SessionProvider } from '../app/providers/SessionProvider';
import { ToastProvider } from '../app/providers/ToastProvider';
import { ExplorePage } from './ExplorePage';

const mocked = vi.hoisted(() => ({ api: vi.fn(), me: vi.fn(), stream: vi.fn() }));

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: mocked.api, me: mocked.me };
});

// 首页发送即触发 Harness；测试只验证页面如何消费事件，不模拟 SSE 传输层。
vi.mock('../lib/harness/session', () => ({ streamSession: mocked.stream }));

vi.mock('../components/explore/ExploreMap', () => ({
  ExploreMap: () => <div data-testid="explore-map" />,
}));

const SESSION = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
  accepted_terms_at: null,
};

const CITY_CENTER = { lon: 120.155, lat: 30.274, city: '杭州' };

const PLACE: Place = {
  id: 'place-1',
  name: '西湖',
  address: '西湖区龙井路',
  location: '120.14,30.24',
  opentime: '全天',
  cost: '免费',
  source_time: '',
  city: '杭州',
};

const PREVIEW: Trip = {
  id: 21,
  request: {
    city: '杭州',
    days: 3,
    start_date: null,
    travelers: 2,
    interests: '',
    pace: '适中',
    budget: '',
    must_visit: '',
    transport: 'transit',
  },
  days: [{ stops: [{ place: PLACE, duration: 90, reason: '西湖边走走' }], routes: [] }],
  backlog: [],
  conversation: [],
  created_at: '2026-11-06T00:00:00Z',
};

const authListeners = new Set<EventListener>();

function watchAuth() {
  const spy = vi.fn();
  authListeners.add(spy);
  window.addEventListener('xingji:open-auth', spy);
  return spy;
}

function renderPage() {
  return render(
    <SessionProvider>
      <DraftProvider>
        <ToastProvider>
          <ExplorePage />
        </ToastProvider>
      </DraftProvider>
    </SessionProvider>,
  );
}

async function renderSignedIn() {
  mocked.me.mockResolvedValue(SESSION);
  const view = renderPage();
  await screen.findByRole('button', { name: '打开个人中心' });
  return view;
}

async function settleGuest() {
  await screen.findByRole('button', { name: '登录' });
  await act(async () => {
    await Promise.resolve();
  });
}

type HarnessEvent = {
  kind: string;
  text?: string;
  reply?: string;
  plan?: Trip;
  message?: string;
  failed?: boolean;
  turn_count?: number;
};

type StreamHandlers = { onEvent?: (event: HarnessEvent) => void; onDone?: (result: { done: boolean; failed: boolean; error?: string }) => void };

function mockStream(events: HarnessEvent[], result: { done: boolean; failed: boolean; error?: string } = { done: true, failed: false }) {
  mocked.stream.mockImplementationOnce((_input: unknown, handlers: StreamHandlers = {}) => {
    for (const event of events) handlers.onEvent?.(event);
    handlers.onDone?.(result);
    return () => undefined;
  });
}

function mockHappyApi() {
  mocked.api.mockImplementation(async (url: string) => {
    if (url.startsWith('/discover/city-center')) return CITY_CENTER;
    if (url.startsWith('/discover/nearby')) return [PLACE];
    throw new Error(`未模拟的请求：${url}`);
  });
}

describe('ExplorePage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    window.history.replaceState(null, '', '#/explore');
    mocked.api.mockReset();
    mocked.me.mockReset();
    mocked.stream.mockReset();
    mocked.me.mockRejectedValue(new ApiError('登录已过期，请重新登录', 401));
    mockHappyApi();
    mocked.stream.mockImplementation((_input: unknown, handlers: StreamHandlers = {}) => {
      handlers.onEvent?.({ kind: 'phase', text: '正在理解你的需求…' });
      handlers.onEvent?.({ kind: 'assistant_delta', text: '好的，我记下了。' });
      handlers.onEvent?.({ kind: 'done', reply: '好的，我记下了。', turn_count: 1 });
      handlers.onDone?.({ done: true, failed: false });
      return () => undefined;
    });
  });

  afterEach(() => {
    for (const listener of authListeners) {
      window.removeEventListener('xingji:open-auth', listener);
    }
    authListeners.clear();
  });

  it('shows the start-here guide in the full sheet when there is no location and no saved place', async () => {
    renderPage();
    expect(await screen.findByTestId('explore-map')).toBeInTheDocument();
    expect(screen.queryByRole('heading', {
      level: 3,
      name: '把想法变成一条能走的路线',
    })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '调整面板高度' }));

    expect(await screen.findByRole('heading', {
      level: 3,
      name: '把想法变成一条能走的路线',
    })).toBeInTheDocument();
  });

  it('loads the city center and nearby places after choosing a city chip', async () => {
    await renderSignedIn();

    fireEvent.click(screen.getByRole('button', { name: '杭州' }));

    await waitFor(() => {
      expect(mocked.api).toHaveBeenCalledWith(
        '/discover/city-center?city=%E6%9D%AD%E5%B7%9E',
        expect.anything(),
      );
    });
    expect(await screen.findByRole('button', { name: '查看西湖' })).toBeInTheDocument();
    expect(mocked.api).toHaveBeenCalledWith(
      '/discover/nearby?lon=120.155&lat=30.274&radius=3000',
      expect.anything(),
    );
    expect(screen.getByRole('button', { name: '杭州' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('sends a submitted message straight to the planning harness', async () => {
    await renderSignedIn();

    fireEvent.change(screen.getByLabelText('说说你想怎么玩'), {
      target: { value: '想去西湖边走走' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    // 发送即触发 Harness，而不是只把消息暂存在本地。
    await waitFor(() => expect(mocked.stream).toHaveBeenCalledTimes(1));
    const input = mocked.stream.mock.calls[0]?.[0] as { message: string; mode: string };
    expect(input.message).toBe('想去西湖边走走');
    expect(input.mode).toBe('explore');

    expect(await screen.findByText('想去西湖边走走')).toBeInTheDocument();
    expect(await screen.findByText('好的，我记下了。')).toBeInTheDocument();
    expect(mocked.api.mock.calls.some(([url]) => url === '/planning/preview')).toBe(false);
  });

  it('shows a retry card when the harness reports a model failure', async () => {
    mockStream([
      { kind: 'error', message: '模型暂时不可用' },
      { kind: 'done', failed: true, turn_count: 1 },
    ], { done: true, failed: true, error: '模型暂时不可用' });
    await renderSignedIn();

    fireEvent.click(screen.getByRole('button', { name: '杭州' }));
    await screen.findByRole('button', { name: '查看西湖' });

    const generateButton = screen.getByRole('button', { name: '生成行程' });
    await waitFor(() => expect(generateButton).toBeEnabled());
    fireEvent.click(generateButton);

    const errorTitle = await screen.findByText('这次没生成成功');
    const alert = errorTitle.closest('[role="alert"]');
    expect(alert).not.toBeNull();
    // 失败原因来自后端 detail：模型/网络问题要如实告诉用户，而不是只给泛化文案。
    expect(alert).toHaveTextContent('模型暂时不可用');
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('asks a guest to log in before saving a preview', async () => {
    const authSpy = watchAuth();
    mockStream([
      { kind: 'plan', plan: PREVIEW },
      { kind: 'done', reply: '路线排好了。', plan: PREVIEW, turn_count: 1 },
    ]);
    renderPage();
    await settleGuest();

    fireEvent.click(screen.getByRole('button', { name: '杭州' }));
    await screen.findByRole('button', { name: '查看西湖' });
    const generateButton = screen.getByRole('button', { name: '生成行程' });
    await waitFor(() => expect(generateButton).toBeEnabled());
    fireEvent.click(generateButton);

    // 生成完成不再自动打开全屏预览：半屏先出结果卡，地图同时在画线。
    expect(await screen.findByText('路线已生成')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('登录后才能保存行程');

    fireEvent.click(screen.getByRole('button', { name: '保存行程' }));

    await waitFor(() => expect(authSpy).toHaveBeenCalledTimes(1));
    const event = authSpy.mock.calls[0][0] as CustomEvent<{ intent: string }>;
    expect(event.detail.intent).toBe('save');
    expect(mocked.api.mock.calls.some(([url]) => url === '/trips/from-preview')).toBe(false);

    // 「查看全部」才打开完整预览。
    fireEvent.click(screen.getByRole('button', { name: '查看全部' }));
    expect(await screen.findByRole('heading', { name: '杭州的路线' })).toBeInTheDocument();
  });
});