import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { SessionProvider } from '../app/providers/SessionProvider';
import { ToastProvider } from '../app/providers/ToastProvider';
import type { MeResponse } from '../lib/api';
import { AccountSettingsPage } from './AccountSettingsPage';

const mocked = vi.hoisted(() => ({
  me: vi.fn(),
  getMemoryPreference: vi.fn(),
}));

vi.mock('../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return {
    ...actual,
    me: mocked.me,
    getMemoryPreference: mocked.getMemoryPreference,
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

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, '', '#/settings/account');
  mocked.me.mockResolvedValue(alice);
  mocked.getMemoryPreference.mockResolvedValue({ enabled: true });
});

describe('AccountSettingsPage', () => {
  it('提供账号数据导出入口，并说明导出范围与不含内容', async () => {
    render(<Providers><AccountSettingsPage /></Providers>);

    expect(await screen.findByRole('heading', { name: '我的数据' })).toBeInTheDocument();
    expect(screen.getByText(/导出账号资料、全部行程（含已删除）、预算花费与 AI 记忆/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出我的数据' })).toBeInTheDocument();
    expect(screen.getByText('导出内容不含密码、登录令牌或分享令牌。')).toBeInTheDocument();
  });
});
