import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api';
import { AuthDialog } from './AuthDialog';

const session = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
}));
const toast = vi.hoisted(() => vi.fn());

vi.mock('../../app/providers/SessionProvider', () => ({
  useSession: () => session,
}));
vi.mock('../../app/providers/ToastProvider', () => ({
  useToast: () => ({ toast }),
}));

const onClose = vi.fn();
const onSuccess = vi.fn();

/** 从 aria-describedby 找到该输入框绑定的错误提示文本。 */
function fieldError(input: HTMLElement): string {
  const describedBy = input.getAttribute('aria-describedby') ?? '';
  const errorId = describedBy.split(' ').find(id => id.endsWith('-error'));
  return errorId ? (document.getElementById(errorId)?.textContent ?? '') : '';
}

function renderDialog(mode: 'login' | 'register' = 'register') {
  render(<AuthDialog open initialMode={mode} onClose={onClose} onSuccess={onSuccess} />);
}

async function fillRegister(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('用户名'), 'alice');
  await user.type(screen.getByLabelText('邮箱'), 'alice@example.com');
  await user.type(screen.getByLabelText('密码'), 'secret123');
  await user.type(screen.getByLabelText('确认密码'), 'secret123');
  await user.click(screen.getByRole('checkbox'));
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe('AuthDialog 注册冲突提示', () => {
  it('服务端说用户名被占用时，错误落在用户名字段而不是邮箱', async () => {
    const user = userEvent.setup();
    session.register.mockRejectedValue(new ApiError('用户名已被使用，请换一个。', 409));
    renderDialog('register');

    await fillRegister(user);
    await user.click(screen.getByRole('button', { name: '注册' }));

    await waitFor(() =>
      expect(fieldError(screen.getByLabelText('用户名'))).toBe('用户名已被使用，请换一个。'),
    );
    expect(screen.getByLabelText('用户名')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('邮箱')).not.toHaveAttribute('aria-invalid');
    expect(screen.queryByText('用户名或邮箱已被使用，请换一个。')).not.toBeInTheDocument();
  });

  it('服务端说邮箱被占用时，错误落在邮箱字段', async () => {
    const user = userEvent.setup();
    session.register.mockRejectedValue(
      new ApiError('这个邮箱已绑定其他账号，请换一个或直接登录。', 409),
    );
    renderDialog('register');

    await fillRegister(user);
    await user.click(screen.getByRole('button', { name: '注册' }));

    await waitFor(() =>
      expect(fieldError(screen.getByLabelText('邮箱'))).toBe(
        '这个邮箱已绑定其他账号，请换一个或直接登录。',
      ),
    );
    expect(screen.getByLabelText('邮箱')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('用户名')).not.toHaveAttribute('aria-invalid');
  });

  it('同时提到用户名和邮箱时不猜字段，落到表单级错误', async () => {
    const user = userEvent.setup();
    session.register.mockRejectedValue(new ApiError('用户名或邮箱已被使用，请换一个。', 409));
    renderDialog('register');

    await fillRegister(user);
    await user.click(screen.getByRole('button', { name: '注册' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('用户名或邮箱已被使用，请换一个。');
    expect(screen.getByLabelText('用户名')).not.toHaveAttribute('aria-invalid');
    expect(screen.getByLabelText('邮箱')).not.toHaveAttribute('aria-invalid');
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('注册成功后回调 onSuccess 并关闭弹层', async () => {
    const user = userEvent.setup();
    session.register.mockResolvedValue({ emailSent: true });
    renderDialog('register');

    await fillRegister(user);
    await user.click(screen.getByRole('button', { name: '注册' }));

    await waitFor(() =>
      expect(session.register).toHaveBeenCalledWith({
        username: 'alice',
        password: 'secret123',
        email: 'alice@example.com',
        accept_terms: true,
      }),
    );
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(toast).not.toHaveBeenCalled();
  });

  it('不填邮箱也能注册，并提示之后可在账户设置绑定', async () => {
    const user = userEvent.setup();
    session.register.mockResolvedValue({ emailSent: false });
    renderDialog('register');

    await user.type(screen.getByLabelText('用户名'), 'alice');
    await user.type(screen.getByLabelText('密码'), 'secret123');
    await user.type(screen.getByLabelText('确认密码'), 'secret123');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: '注册' }));

    await waitFor(() =>
      expect(session.register).toHaveBeenCalledWith({
        username: 'alice',
        password: 'secret123',
        email: '',
        accept_terms: true,
      }),
    );
    expect(screen.getByLabelText('邮箱')).not.toHaveAttribute('aria-invalid');
    expect(toast).toHaveBeenCalledWith('账号已创建。可在账户设置里绑定邮箱，用于找回密码。');
    expect(toast).not.toHaveBeenCalledWith(
      '账号已创建。当前环境未配置邮件服务，验证邮件没有发出。',
    );
  });

  it('注册成功但验证邮件没发出时，关闭弹层并明确提示', async () => {
    const user = userEvent.setup();
    session.register.mockResolvedValue({ emailSent: false });
    renderDialog('register');

    await fillRegister(user);
    await user.click(screen.getByRole('button', { name: '注册' }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(toast).toHaveBeenCalledWith(
      '账号已创建。当前环境未配置邮件服务，验证邮件没有发出。',
    );
  });
});

describe('AuthDialog 登录失败', () => {
  it('401 仍走表单级错误，不污染字段', async () => {
    const user = userEvent.setup();
    session.login.mockRejectedValue(new ApiError('用户名或密码错误', 401));
    renderDialog('login');

    await user.type(screen.getByLabelText('用户名'), 'alice');
    await user.type(screen.getByLabelText('密码'), 'wrongpass');
    await user.click(screen.getByRole('button', { name: '登录' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('用户名或密码错误');
    expect(screen.getByLabelText('用户名')).not.toHaveAttribute('aria-invalid');
    expect(screen.getByLabelText('密码')).not.toHaveAttribute('aria-invalid');
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
