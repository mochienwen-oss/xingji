import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { MeResponse } from '../../lib/api';
import type { Trip } from '../../types/trip';
import { SessionProvider, useSession } from './SessionProvider';
import { ToastProvider } from './ToastProvider';
import { TripEditorProvider, useTripEditor } from './TripEditorProvider';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  me: vi.fn(),
  logout: vi.fn(),
}));

vi.mock('../../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: mocks.api, me: mocks.me, logout: mocks.logout };
});

vi.mock('../../lib/sync', () => ({ pollTripVersion: vi.fn(() => () => {}) }));

vi.mock('../../lib/sessionChannel', () => ({
  broadcastSessionChange: vi.fn(),
  onSessionChange: () => () => {},
}));

const aliceMe: MeResponse = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
  accepted_terms_at: '2026-01-01T00:00:00Z',
};

const trip: Trip = {
  id: 11,
  version: 1,
  title: '审计·杭州三日',
  request: {
    city: '杭州',
    days: 0,
    start_date: null,
    travelers: 2,
    interests: '',
    pace: '适中',
    budget: '',
    must_visit: '',
    transport: 'transit',
  },
  days: [],
  backlog: [],
};

/** 最小 WebSocket 假实现：只用来断言连接是否建立/关闭。 */
class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event?: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event?: { code: number }) => void) | null = null;
  onerror: ((event?: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send() {}

  close(code = 1000) {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }
}

function Probe() {
  const { user, logout } = useSession();
  const { openTrip, live, trip } = useTripEditor();
  return (
    <div>
      <span data-testid="user">{user?.username ?? 'guest'}</span>
      <span data-testid="live">{live.status}</span>
      <span data-testid="trip">{trip?.id ?? 'none'}</span>
      <button type="button" onClick={() => { void openTrip(11); }}>open</button>
      <button type="button" onClick={() => { void logout(); }}>logout</button>
    </div>
  );
}

function renderEditor() {
  return render(
    <SessionProvider>
      <ToastProvider>
        <TripEditorProvider>
          <Probe />
        </TripEditorProvider>
      </ToastProvider>
    </SessionProvider>,
  );
}

describe('TripEditorProvider 实时连接', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    mocks.api.mockReset();
    mocks.me.mockReset().mockResolvedValue(aliceMe);
    mocks.logout.mockReset().mockResolvedValue(undefined);
    mocks.api.mockImplementation((path: unknown) => {
      if (path === '/trips/11') return Promise.resolve(trip);
      return Promise.reject(new Error('unexpected ' + String(path)));
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('退出登录后立即断开实时连接，不会继续显示为在线', async () => {
    renderEditor();
    expect(await screen.findByTestId('user')).toHaveTextContent('alice');

    fireEvent.click(screen.getByRole('button', { name: 'open' }));
    await waitFor(() => expect(screen.getByTestId('trip')).toHaveTextContent('11'));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
    });
    expect(screen.getByTestId('live')).toHaveTextContent('open');

    fireEvent.click(screen.getByRole('button', { name: 'logout' }));
    expect(await screen.findByTestId('user')).toHaveTextContent('guest');

    await waitFor(() => expect(socket.readyState).toBe(FakeWebSocket.CLOSED));
    expect(screen.getByTestId('live')).toHaveTextContent('closed');
    // 旧账号的行程不能留在常驻编辑器里。
    expect(screen.getByTestId('trip')).toHaveTextContent('none');
    // 断开是因为登录态消失，不是网络抖动：不能重连，否则服务端又把他算成在线。
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
