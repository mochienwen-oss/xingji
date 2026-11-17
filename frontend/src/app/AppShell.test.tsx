import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';
import { SessionProvider, useSession } from './providers/SessionProvider';
import { ToastProvider } from './providers/ToastProvider';
import { ApiError, type AuthResponse, type MeResponse } from '../lib/api';
import appSource from './App.tsx?raw';

const mocked = vi.hoisted(() => ({ api: vi.fn(), login: vi.fn(), me: vi.fn() }));

vi.mock('../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: mocked.api, login: mocked.login, me: mocked.me };
});

const channelMock = vi.hoisted(() => ({
  listeners: new Set<(change: { username: string | null }) => void>(),
  broadcast: vi.fn(),
}));

vi.mock('../lib/sessionChannel', () => ({
  broadcastSessionChange: channelMock.broadcast,
  onSessionChange: (listener: (change: { username: string | null }) => void) => {
    channelMock.listeners.add(listener);
    return () => { channelMock.listeners.delete(listener); };
  },
}));

vi.mock('../pages/ExplorePage', () => ({ ExplorePage: () => <div>explore-page</div> }));
vi.mock('../pages/TripsPage', () => ({ TripsPage: ({ tab }: { tab: string }) => <div>trips-page-{tab}</div> }));
vi.mock('../pages/TripWorkspacePage', () => ({ TripWorkspacePage: ({ tripId }: { tripId: number }) => <div>trip-page-{tripId}</div> }));
vi.mock('../pages/CollabPage', () => ({ CollabPage: () => <div>collab-page</div> }));
vi.mock('../pages/ProfilePage', () => ({ ProfilePage: () => <div>profile-page</div> }));
vi.mock('../pages/AccountSettingsPage', () => ({ AccountSettingsPage: () => <div>account-page</div> }));
vi.mock('../pages/SharedTripPage', () => ({ SharedTripPage: ({ token }: { token: string }) => <div>share-page-{token}</div> }));
vi.mock('../pages/auth/ForgotPage', () => ({ ForgotPage: () => <div>forgot-page</div> }));
vi.mock('../pages/auth/ResetPage', () => ({ ResetPage: () => <div>reset-page</div> }));
vi.mock('../pages/auth/VerifyPage', () => ({ VerifyPage: () => <div>verify-page</div> }));
vi.mock('../pages/auth/TermsPage', () => ({ TermsPage: () => <div>terms-page</div> }));
vi.mock('../pages/auth/PrivacyPage', () => ({ PrivacyPage: () => <div>privacy-page</div> }));

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

/** 走真实 SessionProvider.login()：登录响应 + 随后的 /me 刷新会连续两次替换 user 身份。 */
function SessionLoginProbe() {
  const { login } = useSession();
  return <button type="button" onClick={() => { void login('alice', 'secret'); }}>probe-login</button>;
}

function renderShell(hash: string, withLoginProbe = false) {
  window.history.replaceState(null, '', hash);
  return render(
    <SessionProvider>
      <ToastProvider>
        {withLoginProbe ? <SessionLoginProbe /> : null}
        <AppShell />
      </ToastProvider>
    </SessionProvider>,
  );
}

describe('AppShell', () => {
  beforeEach(() => {
    mocked.me.mockReset();
    mocked.me.mockRejectedValue(new ApiError('请先登录', 401));
    mocked.api.mockReset();
    mocked.login.mockReset();
    channelMock.listeners.clear();
    channelMock.broadcast.mockReset();
  });

  it('marks the active tab for the current hash', async () => {
    renderShell('#/trips');
    const link = await screen.findByRole('link', { name: '行程' });
    expect(link).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('trips-page-mine')).toBeInTheDocument();
  });

  it('renders the collab page with 协同 as the active tab', async () => {
    renderShell('#/collab');
    expect(await screen.findByText('collab-page')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: '协同' });
    expect(link).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: '行程' })).not.toHaveAttribute('aria-current');
  });

  it('navigates when a bottom tab is clicked', async () => {
    renderShell('#/explore');
    const profile = await screen.findByRole('link', { name: '我的' });
    fireEvent.click(profile);
    expect(await screen.findByText('profile-page')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/profile');
  });

  it('keeps the explore page mounted but hidden when switching tabs', async () => {
    renderShell('#/explore');
    const explore = await screen.findByText('explore-page');
    expect(explore.closest('[hidden]')).toBeNull();

    fireEvent.click(screen.getByRole('link', { name: '我的' }));
    expect(await screen.findByText('profile-page')).toBeInTheDocument();
    // 生成中的规划流绑在探索页组件上；切 tab 只能隐藏，不能卸载。
    expect(explore).toBeInTheDocument();
    expect(explore.closest('[hidden]')).not.toBeNull();

    fireEvent.click(screen.getByRole('link', { name: '探索' }));
    expect(await screen.findByText('explore-page')).toBe(explore);
    expect(explore.closest('[hidden]')).toBeNull();
  });

  it('renders a share page without app navigation', async () => {
    renderShell('#share=abc123');
    expect(await screen.findByText('share-page-abc123')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument();
  });

  it('keeps App.tsx as a provider-only composition', () => {
    expect(appSource.split('\n').length).toBeLessThanOrEqual(80);
  });

  it('shows the not-found page for an unknown route', async () => {
    renderShell('#/nope');
    expect(await screen.findByText('这条路线不存在。')).toBeInTheDocument();
  });

  it('lands the invite accept after login replaces the user identity twice', async () => {
    // /me 挂起成受控 Promise：登录响应（第一份 user）先独立提交一次渲染、触发 accept，
    // 然后 /me 刷新（第二份 user）才落地。两次身份替换必须各自提交，才能复现 P1。
    let resolveMe!: (value: MeResponse) => void;
    mocked.me.mockRejectedValueOnce(new ApiError('未登录', 401)).mockImplementation(
      () => new Promise<MeResponse>(resolve => { resolveMe = resolve; }),
    );
    mocked.login.mockResolvedValue(aliceAuth);
    let resolveAccept!: (value: { trip_id: number; title: string | null; city: string }) => void;
    mocked.api.mockImplementation(() => new Promise<{ trip_id: number; title: string | null; city: string }>(resolve => {
      resolveAccept = resolve;
    }));

    renderShell('#invite=tok123', true);
    // 游客态停在登录引导，不会自动 accept。
    expect(await screen.findByText('登录 / 注册')).toBeInTheDocument();
    expect(mocked.api).not.toHaveBeenCalled();

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'probe-login' })); });
    // login() 先把登录响应写进 user：第一次身份替换已提交，accept 只发起一次，busy 显示。
    await waitFor(() => {
      expect(mocked.api).toHaveBeenCalledTimes(1);
      expect(mocked.me).toHaveBeenCalledTimes(2);
      expect(screen.getByText('正在接受邀请…')).toBeInTheDocument();
    });
    expect(mocked.api).toHaveBeenCalledWith('/collaborators/accept', {
      method: 'POST',
      body: JSON.stringify({ token: 'tok123' }),
    });

    // accept 挂起期间，/me 刷新把 user 换成第二个身份对象。
    await act(async () => { resolveMe(aliceMe); });

    // accept 结果必须落地：跳转 + toast，busy 结束（旧实现在这里把结果整个丢弃）。
    await act(async () => { resolveAccept({ trip_id: 42, title: null, city: '杭州' }); });

    expect(await screen.findByText('trip-page-42')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/trips/42');
    expect(screen.getByText('已接受邀请，正在打开行程')).toBeInTheDocument();
    expect(screen.queryByText('正在接受邀请…')).not.toBeInTheDocument();
    expect(mocked.api).toHaveBeenCalledTimes(1);
  });

  it('points a consumed invite link to the shared tab instead of a dead end', async () => {
    mocked.me.mockRejectedValueOnce(new ApiError('未登录', 401)).mockResolvedValue(aliceMe);
    mocked.login.mockResolvedValue(aliceAuth);
    mocked.api.mockRejectedValue(new ApiError('邀请链接无效或已被移除。', 404));

    renderShell('#invite=used-up', true);
    expect(await screen.findByText('登录 / 注册')).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'probe-login' })); });

    await waitFor(() => expect(mocked.api).toHaveBeenCalledWith('/collaborators/accept', {
      method: 'POST',
      body: JSON.stringify({ token: 'used-up' }),
    }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('邀请链接已被使用或已失效。如果你刚接受过邀请，请到「协同」查看这份行程。');
    expect(screen.queryByText('正在接受邀请…')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('tells the user when another tab switched the signed-in account', async () => {
    mocked.me.mockResolvedValue(aliceMe);
    renderShell('#/trips');
    await screen.findByText('trips-page-mine');
    await waitFor(() => expect(mocked.me).toHaveBeenCalled());
    await act(async () => {});

    act(() => {
      for (const listener of channelMock.listeners) listener({ username: 'bob' });
    });

    expect(await screen.findByText('另一个标签页已登录「bob」，本页已同步切换')).toBeInTheDocument();
  });

  it('tells the user when another tab signed out', async () => {
    mocked.me.mockResolvedValue(aliceMe);
    renderShell('#/trips');
    await screen.findByText('trips-page-mine');
    await waitFor(() => expect(mocked.me).toHaveBeenCalled());
    await act(async () => {});

    act(() => {
      for (const listener of channelMock.listeners) listener({ username: null });
    });

    expect(await screen.findByText('另一个标签页已退出登录，本页已同步。')).toBeInTheDocument();
  });
});