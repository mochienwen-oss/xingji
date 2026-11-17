import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { SessionProvider } from '../../app/providers/SessionProvider';
import { ToastProvider } from '../../app/providers/ToastProvider';
import { ApiError, type MeResponse } from '../../lib/api';
import { AccountSettingsPage } from '../AccountSettingsPage';
import { ForgotPage } from './ForgotPage';
import { PrivacyPage } from './PrivacyPage';
import { ResetPage } from './ResetPage';
import { TermsPage } from './TermsPage';
import { VerifyPage } from './VerifyPage';

const mocked = vi.hoisted(() => ({
  me: vi.fn(),
  logout: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  forgotPassword: vi.fn(),
  resetPassword: vi.fn(),
  verifyEmail: vi.fn(),
  resendEmail: vi.fn(),
  changeEmail: vi.fn(),
  changePassword: vi.fn(),
  acceptTerms: vi.fn(),
  deleteAccount: vi.fn(),
}));

vi.mock('../../lib/legal', () => ({
  useOperatorInfo: () => ({
    name: '杭州行迹科技有限公司',
    contact_email: 'legal@xingji.example',
    jurisdiction: '杭州市西湖区',
    icp_number: '浙ICP备2026000000号',
  }),
}));

vi.mock('../../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return {
    ...actual,
    me: mocked.me,
    logout: mocked.logout,
    login: mocked.login,
    register: mocked.register,
    forgotPassword: mocked.forgotPassword,
    resetPassword: mocked.resetPassword,
    verifyEmail: mocked.verifyEmail,
    resendEmail: mocked.resendEmail,
    changeEmail: mocked.changeEmail,
    changePassword: mocked.changePassword,
    acceptTerms: mocked.acceptTerms,
    deleteAccount: mocked.deleteAccount,
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

function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <ToastProvider>{children}</ToastProvider>
    </SessionProvider>
  );
}

function goTo(hash: string) {
  window.history.replaceState(null, '', hash);
}

beforeEach(() => {
  vi.resetAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
  goTo('#/explore');
  mocked.me.mockRejectedValue(new ApiError('未登录', 401));
});

describe('ForgotPage', () => {
  it('不暴露账号是否存在：请求失败也显示统一成功文案，并进入 60 秒冷却', async () => {
    const user = userEvent.setup();
    mocked.forgotPassword.mockRejectedValue(new ApiError('账号不存在', 404));
    goTo('#/forgot');

    render(<Providers><ForgotPage /></Providers>);

    await user.type(screen.getByLabelText('用户名或邮箱'), 'alice@example.com');
    await user.click(screen.getByRole('button', { name: '发送重置链接' }));

    await waitFor(() =>
      expect(mocked.forgotPassword).toHaveBeenCalledWith('alice@example.com'),
    );
    expect(await screen.findByText('如果账号存在，我们已发送重置链接')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /秒后可重新发送/ })).toBeDisabled();
  });
});

describe('ResetPage', () => {
  it('两次输入的密码不一致时提示，并且不请求后端', async () => {
    const user = userEvent.setup();
    goTo('#/reset=tok');

    render(<Providers><ResetPage token="tok" /></Providers>);

    await user.type(screen.getByLabelText('新密码', { selector: 'input' }), 'secret123');
    await user.type(screen.getByLabelText('确认新密码', { selector: 'input' }), 'secret124');
    await user.click(screen.getByRole('button', { name: '更新密码' }));

    expect(screen.getAllByText('两次输入的密码不一致。').length).toBeGreaterThan(0);
    expect(mocked.resetPassword).not.toHaveBeenCalled();
  });

  it('重置成功后清掉本地行迹数据、退出登录并回到探索页', async () => {
    const user = userEvent.setup();
    mocked.resetPassword.mockResolvedValue({ ok: true });
    mocked.logout.mockResolvedValue(undefined);
    window.sessionStorage.setItem('xingji-draft:guest', '{"places":[]}');
    goTo('#/reset=tok');

    render(<Providers><ResetPage token="tok" /></Providers>);

    await user.type(screen.getByLabelText('新密码', { selector: 'input' }), 'secret123');
    await user.type(screen.getByLabelText('确认新密码', { selector: 'input' }), 'secret123');
    await user.click(screen.getByRole('button', { name: '更新密码' }));

    await waitFor(() =>
      expect(mocked.resetPassword).toHaveBeenCalledWith({ token: 'tok', new_password: 'secret123' }),
    );
    await waitFor(() => expect(window.location.hash).toBe('#/explore'));
    expect(mocked.logout).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem('xingji-draft:guest')).toBeNull();
  });

  it('链接失效时给出重新申请入口', async () => {
    const user = userEvent.setup();
    mocked.resetPassword.mockRejectedValue(new ApiError('token 无效', 400));
    goTo('#/reset=tok');

    render(<Providers><ResetPage token="tok" /></Providers>);

    await user.type(screen.getByLabelText('新密码', { selector: 'input' }), 'secret123');
    await user.type(screen.getByLabelText('确认新密码', { selector: 'input' }), 'secret123');
    await user.click(screen.getByRole('button', { name: '更新密码' }));

    expect(await screen.findByText('链接无效或已过期')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新申请' })).toBeInTheDocument();
  });
});

describe('VerifyPage', () => {
  it('验证成功后显示已绑定邮箱、清理待验证缓存并刷新会话', async () => {
    const user = userEvent.setup();
    mocked.me.mockResolvedValue({ ...alice, email: 'old@example.com', email_verified: false });
    mocked.verifyEmail.mockResolvedValue({
      ok: true,
      email: 'new@example.com',
      kind: 'change_email',
    });
    const key = 'xingji-pending-email:alice';
    window.localStorage.setItem(key, 'new@example.com');
    goTo('#/verify=tok');

    render(<Providers><VerifyPage token="tok" /></Providers>);

    expect(await screen.findByRole('heading', { name: '邮箱已验证' })).toBeInTheDocument();
    expect(mocked.verifyEmail).toHaveBeenCalledWith('tok');
    expect(await screen.findByText(/new@example.com/)).toBeInTheDocument();
    await waitFor(() => expect(window.localStorage.getItem(key)).toBeNull());
    await waitFor(() => expect(mocked.me).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole('button', { name: '去我的' }));
    expect(window.location.hash).toBe('#/profile');
  });

  it('失效链接显示验证失败与统一提示', async () => {
    mocked.verifyEmail.mockRejectedValue(new ApiError('链接无效或已过期', 400));
    goTo('#/verify=bad');

    render(<Providers><VerifyPage token="bad" /></Providers>);

    expect(await screen.findByRole('heading', { name: '验证失败' })).toBeInTheDocument();
    expect(screen.getByText('链接无效或已过期')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新发送验证邮件' })).toBeInTheDocument();
  });
});

describe('TermsPage', () => {
  it('渲染条款正文，返回时回到来源页并保留来源参数', async () => {
    const user = userEvent.setup();
    goTo('#/terms?from=account');

    render(<TermsPage />);

    expect(screen.getByRole('heading', { level: 1, name: '服务条款' })).toBeInTheDocument();
    expect(screen.getByText(/运营主体：杭州行迹科技有限公司/)).toHaveTextContent('杭州市西湖区');
    for (const link of screen.getAllByRole('link', { name: '隐私政策' })) {
      expect(link).toHaveAttribute('href', '#/privacy?from=account');
    }

    await user.click(screen.getByRole('button', { name: '返回' }));
    expect(window.location.hash).toBe('#/settings/account');
  });
});

describe('PrivacyPage', () => {
  it('展示配置的运营主体与联系方式', () => {
    goTo('#/privacy?from=account');
    render(<PrivacyPage />);

    expect(screen.getByRole('heading', { level: 1, name: '隐私政策' })).toBeInTheDocument();
    expect(screen.getByText(/运营主体：杭州行迹科技有限公司/)).toHaveTextContent('legal@xingji.example');
  });
});

describe('AccountSettingsPage 待验证邮箱', () => {
  it('修改邮箱后显示待验证地址并写入本地缓存', async () => {
    const user = userEvent.setup();
    mocked.me.mockResolvedValue(alice);
    mocked.changeEmail.mockResolvedValue({ pending_email: 'new@example.com', email_sent: true });
    goTo('#/settings/account');

    render(<Providers><AccountSettingsPage /></Providers>);

    expect(await screen.findByRole('heading', { name: '账户设置' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '修改邮箱' }));

    const emailCard = screen.getByRole('region', { name: '邮箱' });
    await user.type(within(emailCard).getByLabelText('新邮箱'), 'new@example.com');
    await user.type(within(emailCard).getByLabelText('当前密码'), 'secret123');
    await user.click(within(emailCard).getByRole('button', { name: '发送验证邮件' }));

    await waitFor(() =>
      expect(mocked.changeEmail).toHaveBeenCalledWith({
        email: 'new@example.com',
        password: 'secret123',
      }),
    );
    expect(await screen.findByText('待验证：')).toBeInTheDocument();
    expect(screen.getByText('new@example.com')).toBeInTheDocument();
    expect(window.localStorage.getItem('xingji-pending-email:alice')).toBe('new@example.com');
  });

  it('刷新后从 localStorage 读回待验证邮箱', async () => {
    mocked.me.mockResolvedValue(alice);
    window.localStorage.setItem('xingji-pending-email:alice', 'pending@example.com');
    goTo('#/settings/account');

    render(<Providers><AccountSettingsPage /></Providers>);

    expect(await screen.findByText('pending@example.com')).toBeInTheDocument();
    expect(screen.getByText('待验证：')).toBeInTheDocument();
  });

  it('新邮箱验证通过后清掉缓存，不再显示待验证', async () => {
    mocked.me.mockResolvedValue({
      ...alice,
      email: 'new@example.com',
      email_verified: true,
    });
    const key = 'xingji-pending-email:alice';
    window.localStorage.setItem(key, 'new@example.com');
    goTo('#/settings/account');

    render(<Providers><AccountSettingsPage /></Providers>);

    await waitFor(() => expect(window.localStorage.getItem(key)).toBeNull());
    expect(screen.queryByText('待验证：')).not.toBeInTheDocument();
    expect(screen.getByText('已验证')).toBeInTheDocument();
  });
});
