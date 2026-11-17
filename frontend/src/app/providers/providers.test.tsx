import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import type { ReactNode } from 'react';
import {
  ApiError,
  api,
  login,
  logout,
  me,
  register,
  type AuthResponse,
  type MeResponse,
} from '../../lib/api';
import { broadcastSessionChange, onSessionChange } from '../../lib/sessionChannel';
import type { DeletedTrip, PlanRequest, TripSummary } from '../../types/trip';
import { draftStorageKey, DraftProvider, useDraft } from './DraftProvider';
import { SessionProvider, useSession } from './SessionProvider';
import {
  TripListProvider,
  tripCacheKey,
  useTripList,
} from './TripListProvider';

vi.mock('../../lib/api', () => {
  class ApiError extends Error {
    readonly status: number;
    constructor(text: string, status: number) {
      super(text);
      this.name = 'ApiError';
      this.status = status;
    }
  }
  return {
    ApiError,
    api: vi.fn(),
    me: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    message: (error: unknown) => (error instanceof Error ? error.message : '请求失败，请稍后再试。'),
  };
});

const sessionChannelMock = vi.hoisted(() => ({
  listeners: new Set<(change: { username: string | null }) => void>(),
}));

vi.mock('../../lib/sessionChannel', () => ({
  broadcastSessionChange: vi.fn(),
  onSessionChange: vi.fn((listener: (change: { username: string | null }) => void) => {
    sessionChannelMock.listeners.add(listener);
    return () => {
      sessionChannelMock.listeners.delete(listener);
    };
  }),
}));

const aliceMe: MeResponse = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
  accepted_terms_at: '2026-01-01T00:00:00Z',
};

const aliceAuth: AuthResponse = {
  username: 'alice',
  email: 'alice@example.com',
  email_verified: true,
  needs_terms: false,
  needs_email: false,
};

function SessionOnly({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}

function AllProviders({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <DraftProvider>{children}</DraftProvider>
    </SessionProvider>
  );
}

function SessionProbe() {
  const {
    user,
    loading,
    login: signIn,
    register: signUp,
    logout: signOut,
    refresh,
  } = useSession();
  return (
    <div>
      <span data-testid="session-state">
        {loading ? 'loading' : user ? `user:${user.username}` : 'guest'}
      </span>
      <span data-testid="email">{user?.email ?? ''}</span>
      <span data-testid="email-verified">{String(user?.emailVerified)}</span>
      <span data-testid="needs-email">{String(user?.needsEmail)}</span>
      <span data-testid="needs-terms">{String(user?.needsTerms)}</span>
      <button type="button" onClick={() => { void signIn('alice', 'secret'); }}>login</button>
      <button
        type="button"
        onClick={() => {
          void signUp({
            username: 'alice',
            password: 'secret',
            email: 'alice@example.com',
            accept_terms: true,
          });
        }}
      >
        register
      </button>
      <button type="button" onClick={() => { void signOut(); }}>logout</button>
      <button type="button" onClick={() => { void refresh(); }}>refresh</button>
    </div>
  );
}

function DraftProbe() {
  const {
    ownerKey,
    form,
    messages,
    places,
    setForm,
    clearDraft,
  } = useDraft();
  return (
    <div>
      <span data-testid="draft-owner">{ownerKey}</span>
      <span data-testid="draft-city">{form.city}</span>
      <span data-testid="draft-messages">{messages.length}</span>
      <span data-testid="draft-places">{places.length}</span>
      <button
        type="button"
        onClick={() => setForm((current) => ({ ...current, city: '游客改' }))}
      >
        guest-city
      </button>
      <button
        type="button"
        onClick={() => setForm((current) => ({ ...current, city: 'alice改' }))}
      >
        alice-city
      </button>
      <button type="button" onClick={clearDraft}>clear-draft</button>
    </div>
  );
}

function planFor(city: string): PlanRequest {
  return {
    city,
    days: 3,
    start_date: null,
    travelers: 2,
    interests: '',
    pace: '适中',
    budget: '',
    must_visit: '',
    transport: 'transit',
  };
}

function tripSummary(id: number, city: string): TripSummary {
  return { id, city, title: null, request: planFor(city) };
}

function deletedTrip(id: number, city: string): DeletedTrip {
  return { id, city, title: null, deleted_at: '2026-01-01T00:00:00Z' };
}

const apiMock = api as unknown as Mock;

function TripProviders({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <TripListProvider>{children}</TripListProvider>
    </SessionProvider>
  );
}

function TripListProbe() {
  const {
    trips,
    deleted,
    loading,
    error,
    refresh,
    restore,
  } = useTripList();
  return (
    <div>
      <span data-testid="trip-cities">{trips.map((trip) => trip.city).join('|')}</span>
      <span data-testid="deleted-cities">{deleted.map((trip) => trip.city).join('|')}</span>
      <span data-testid="trip-loading">{String(loading)}</span>
      <span data-testid="trip-error">{error}</span>
      <button type="button" onClick={() => { void refresh(); }}>refresh-trips</button>
      <button type="button" onClick={() => { void restore(2); }}>restore</button>
    </div>
  );
}

function readStoredCity(storage: Storage, owner: string): string {
  const raw = storage.getItem(draftStorageKey(owner));
  if (!raw) return '';
  const parsed = JSON.parse(raw) as { form?: { city?: string } };
  return parsed.form?.city ?? '';
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  sessionChannelMock.listeners.clear();
  vi.resetAllMocks();
});

describe('SessionProvider', () => {
  it('maps snake_case /api/me into camelCase SessionUser', async () => {
    vi.mocked(me).mockResolvedValue(aliceMe);
    render(<SessionOnly><SessionProbe /></SessionOnly>);

    expect(await screen.findByText('user:alice')).toBeInTheDocument();
    expect(screen.getByTestId('email')).toHaveTextContent('alice@example.com');
    expect(screen.getByTestId('email-verified')).toHaveTextContent('true');
    expect(screen.getByTestId('needs-email')).toHaveTextContent('false');
    expect(screen.getByTestId('needs-terms')).toHaveTextContent('false');
    expect(me).toHaveBeenCalledTimes(1);
  });

  it('exposes needsEmail and needsTerms for incomplete accounts', async () => {
    vi.mocked(me).mockResolvedValue({
      username: 'bob',
      email: null,
      email_verified: false,
      needs_terms: true,
      needs_email: true,
      accepted_terms_at: null,
    });
    render(<SessionOnly><SessionProbe /></SessionOnly>);

    expect(await screen.findByText('user:bob')).toBeInTheDocument();
    expect(screen.getByTestId('email').textContent).toBe('');
    expect(screen.getByTestId('needs-email')).toHaveTextContent('true');
    expect(screen.getByTestId('needs-terms')).toHaveTextContent('true');
  });

  it('treats an initial 401 as a guest without throwing', async () => {
    vi.mocked(me).mockRejectedValue(new ApiError('登录已过期', 401));
    render(<SessionOnly><SessionProbe /></SessionOnly>);

    expect(await screen.findByText('guest')).toBeInTheDocument();
    expect(screen.getByTestId('email').textContent).toBe('');
  });

  it('clears the user when xingji:unauthorized fires', async () => {
    vi.mocked(me).mockResolvedValue(aliceMe);
    render(<SessionOnly><SessionProbe /></SessionOnly>);
    expect(await screen.findByText('user:alice')).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new CustomEvent('xingji:unauthorized'));
    });

    expect(await screen.findByText('guest')).toBeInTheDocument();
    expect(screen.getByTestId('email').textContent).toBe('');
  });

  it('refreshes after login and clears the user on logout', async () => {
    vi.mocked(me).mockRejectedValueOnce(new ApiError('未登录', 401)).mockResolvedValue(aliceMe);
    vi.mocked(login).mockResolvedValue(aliceAuth);
    vi.mocked(logout).mockResolvedValue();
    render(<SessionOnly><SessionProbe /></SessionOnly>);
    expect(await screen.findByText('guest')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'login' }));
    expect(await screen.findByText('user:alice')).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith({ username: 'alice', password: 'secret' });
    expect(me).toHaveBeenCalledTimes(2);
    expect(broadcastSessionChange).toHaveBeenCalledWith('alice');

    fireEvent.click(screen.getByRole('button', { name: 'logout' }));
    expect(await screen.findByText('guest')).toBeInTheDocument();
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    expect(broadcastSessionChange).toHaveBeenCalledWith(null);
  });

  it('refreshes after register', async () => {
    vi.mocked(me).mockRejectedValueOnce(new ApiError('未登录', 401)).mockResolvedValue({
      ...aliceMe,
      email_verified: false,
      needs_email: false,
      needs_terms: false,
    });
    vi.mocked(register).mockResolvedValue({
      ...aliceAuth,
      email_verified: false,
      email_sent: true,
    });
    render(<SessionOnly><SessionProbe /></SessionOnly>);
    expect(await screen.findByText('guest')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'register' }));
    expect(await screen.findByText('user:alice')).toBeInTheDocument();
    expect(register).toHaveBeenCalledWith({
      username: 'alice',
      password: 'secret',
      email: 'alice@example.com',
      accept_terms: true,
    });
    expect(me).toHaveBeenCalledTimes(2);
    expect(broadcastSessionChange).toHaveBeenCalledWith('alice');
  });

  it('re-fetches /api/me when another tab signs in', async () => {
    vi.mocked(me)
      .mockRejectedValueOnce(new ApiError('未登录', 401))
      .mockResolvedValue({ ...aliceMe, username: 'auditxj02' });
    const view = render(<SessionOnly><SessionProbe /></SessionOnly>);
    expect(await screen.findByText('guest')).toBeInTheDocument();
    expect(me).toHaveBeenCalledTimes(1);
    expect(onSessionChange).toHaveBeenCalled();

    await act(async () => {
      for (const listener of [...sessionChannelMock.listeners]) listener({ username: 'auditxj02' });
    });

    expect(await screen.findByText('user:auditxj02')).toBeInTheDocument();
    expect(me).toHaveBeenCalledTimes(2);

    view.unmount();
    expect(sessionChannelMock.listeners.size).toBe(0);
  });

  it('returns to guest when another tab logs out', async () => {
    vi.mocked(me).mockResolvedValueOnce(aliceMe).mockRejectedValue(new ApiError('登录已过期', 401));
    render(<SessionOnly><SessionProbe /></SessionOnly>);
    expect(await screen.findByText('user:alice')).toBeInTheDocument();

    await act(async () => {
      for (const listener of [...sessionChannelMock.listeners]) listener({ username: null });
    });

    expect(await screen.findByText('guest')).toBeInTheDocument();
    expect(me).toHaveBeenCalledTimes(2);
  });
});

describe('TripListProvider', () => {
  it('uses a fresh per-user cache without hitting the network', async () => {
    window.sessionStorage.setItem(tripCacheKey('alice'), JSON.stringify({
      trips: [tripSummary(1, '杭州')],
      deleted: [],
      savedAt: Date.now(),
    }));
    vi.mocked(me).mockResolvedValue(aliceMe);

    render(<TripProviders><TripListProbe /></TripProviders>);
    await waitFor(() => expect(screen.getByTestId('trip-cities')).toHaveTextContent('杭州'));
    expect(screen.getByTestId('trip-loading')).toHaveTextContent('false');
    expect(apiMock).not.toHaveBeenCalled();
  });

  it('ignores a stale cache and fetches both trip lists', async () => {
    window.sessionStorage.setItem(tripCacheKey('alice'), JSON.stringify({
      trips: [tripSummary(1, '杭州')],
      deleted: [],
      savedAt: Date.now() - 120_000,
    }));
    apiMock.mockImplementation((url: string) => Promise.resolve(
      url === '/trips' ? [tripSummary(2, '北京')] : [],
    ));
    vi.mocked(me).mockResolvedValue(aliceMe);

    render(<TripProviders><TripListProbe /></TripProviders>);
    await waitFor(() => expect(screen.getByTestId('trip-cities')).toHaveTextContent('北京'));
    expect(apiMock).toHaveBeenCalledWith('/trips');
    expect(apiMock).toHaveBeenCalledWith('/trips?deleted=true');
  });

  it('clears the list and cache when the account logs out', async () => {
    window.sessionStorage.setItem(tripCacheKey('alice'), JSON.stringify({
      trips: [tripSummary(1, '杭州')],
      deleted: [deletedTrip(2, '苏州')],
      savedAt: Date.now(),
    }));
    vi.mocked(me).mockResolvedValue(aliceMe);
    vi.mocked(logout).mockResolvedValue();

    render(<TripProviders><SessionProbe /><TripListProbe /></TripProviders>);
    await waitFor(() => expect(screen.getByTestId('trip-cities')).toHaveTextContent('杭州'));
    fireEvent.click(screen.getByRole('button', { name: 'logout' }));
    await waitFor(() => expect(screen.getByTestId('session-state')).toHaveTextContent('guest'));
    await waitFor(() => expect(screen.getByTestId('trip-cities').textContent).toBe(''));
    expect(window.sessionStorage.getItem(tripCacheKey('alice'))).toBeNull();
  });

  it('refreshes both lists after restore', async () => {
    apiMock.mockImplementation((url: string) => {
      if (url === '/trips') return Promise.resolve([tripSummary(1, '杭州'), tripSummary(2, '苏州')]);
      if (url === '/trips?deleted=true') return Promise.resolve([deletedTrip(3, '南京')]);
      return Promise.resolve({});
    });
    vi.mocked(me).mockResolvedValue(aliceMe);

    render(<TripProviders><TripListProbe /></TripProviders>);
    await waitFor(() => expect(screen.getByTestId('trip-cities')).toHaveTextContent('杭州'));
    expect(screen.getByTestId('deleted-cities')).toHaveTextContent('南京');

    fireEvent.click(screen.getByRole('button', { name: 'restore' }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith('/trips/2/restore', { method: 'POST' }));
    await waitFor(() => expect(
      apiMock.mock.calls.filter((call) => call[0] === '/trips'),
    ).toHaveLength(2));
  });
});

describe('DraftProvider', () => {
  it('keeps guest and alice drafts isolated when the owner changes', async () => {
    window.sessionStorage.setItem(draftStorageKey('guest'), JSON.stringify({
      form: { city: '游客城市' },
      messages: [{ role: 'user', content: 'guest' }],
      places: [],
    }));
    window.localStorage.setItem(draftStorageKey('alice'), JSON.stringify({
      form: { city: 'alice城市' },
      messages: [{ role: 'assistant', content: 'alice' }, { role: 'user', content: 'alice2' }],
      places: [],
    }));
    vi.mocked(me).mockRejectedValueOnce(new ApiError('未登录', 401)).mockResolvedValue(aliceMe);
    vi.mocked(login).mockResolvedValue(aliceAuth);

    render(<AllProviders><SessionProbe /><DraftProbe /></AllProviders>);
    await waitFor(() => expect(screen.getByTestId('session-state')).toHaveTextContent('guest'));
    await waitFor(() => expect(screen.getByTestId('draft-city')).toHaveTextContent('游客城市'));
    expect(screen.getByTestId('draft-messages')).toHaveTextContent('1');

    fireEvent.click(screen.getByRole('button', { name: 'guest-city' }));
    await waitFor(() => expect(readStoredCity(window.sessionStorage, 'guest')).toBe('游客改'));

    fireEvent.click(screen.getByRole('button', { name: 'login' }));
    await waitFor(() => expect(screen.getByTestId('session-state')).toHaveTextContent('user:alice'));
    await waitFor(() => expect(screen.getByTestId('draft-owner')).toHaveTextContent('alice'));
    await waitFor(() => expect(screen.getByTestId('draft-city')).toHaveTextContent('alice城市'));
    expect(screen.getByTestId('draft-messages')).toHaveTextContent('2');

    fireEvent.click(screen.getByRole('button', { name: 'alice-city' }));
    await waitFor(() => expect(readStoredCity(window.localStorage, 'alice')).toBe('alice改'));
    expect(readStoredCity(window.sessionStorage, 'guest')).toBe('游客改');

    fireEvent.click(screen.getByRole('button', { name: 'clear-draft' }));
    await waitFor(() => expect(window.localStorage.getItem(draftStorageKey('alice'))).toBeNull());
    expect(readStoredCity(window.sessionStorage, 'guest')).toBe('游客改');
  });

  it('migrates an unsaved guest draft into the account on sign-in', async () => {
    window.sessionStorage.setItem(draftStorageKey('guest'), JSON.stringify({
      form: { city: '游客城市' },
      messages: [{ role: 'user', content: '帮我排一下杭州' }],
      places: [],
    }));
    vi.mocked(me).mockRejectedValueOnce(new ApiError('未登录', 401));
    vi.mocked(login).mockResolvedValue(aliceAuth);

    render(<AllProviders><SessionProbe /><DraftProbe /></AllProviders>);
    await waitFor(() => expect(screen.getByTestId('session-state')).toHaveTextContent('guest'));
    await waitFor(() => expect(screen.getByTestId('draft-city')).toHaveTextContent('游客城市'));

    fireEvent.click(screen.getByRole('button', { name: 'login' }));

    await waitFor(() => expect(screen.getByTestId('session-state')).toHaveTextContent('user:alice'));
    await waitFor(() => expect(screen.getByTestId('draft-owner')).toHaveTextContent('alice'));
    await waitFor(() => expect(screen.getByTestId('draft-city')).toHaveTextContent('游客城市'));
    expect(screen.getByTestId('draft-messages')).toHaveTextContent('1');
    await waitFor(() => expect(readStoredCity(window.localStorage, 'alice')).toBe('游客城市'));
    expect(window.sessionStorage.getItem(draftStorageKey('guest'))).toBeNull();
  });

  it('keeps the account draft when both guest and account drafts exist', async () => {
    window.sessionStorage.setItem(draftStorageKey('guest'), JSON.stringify({
      form: { city: '游客城市' },
      messages: [{ role: 'user', content: 'guest' }],
    }));
    window.localStorage.setItem(draftStorageKey('alice'), JSON.stringify({
      form: { city: 'alice城市' },
      messages: [{ role: 'assistant', content: 'alice' }],
    }));
    vi.mocked(me).mockRejectedValueOnce(new ApiError('未登录', 401));
    vi.mocked(login).mockResolvedValue(aliceAuth);

    render(<AllProviders><SessionProbe /><DraftProbe /></AllProviders>);
    await waitFor(() => expect(screen.getByTestId('session-state')).toHaveTextContent('guest'));
    fireEvent.click(screen.getByRole('button', { name: 'login' }));

    await waitFor(() => expect(screen.getByTestId('draft-city')).toHaveTextContent('alice城市'));
    expect(window.sessionStorage.getItem(draftStorageKey('guest'))).not.toBeNull();
  });
});
