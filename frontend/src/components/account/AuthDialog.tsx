import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useSession } from '../../app/providers/SessionProvider';
import { useToast } from '../../app/providers/ToastProvider';
import { useHashRoute } from '../../app/routing/useHashRoute';
import { ApiError, message } from '../../lib/api';
import { Button } from '../ui/Button';
import { Checkbox } from '../ui/Checkbox';
import { Dialog } from '../ui/Dialog';
import { PasswordField } from '../ui/PasswordField';
import { SegmentedControl } from '../ui/SegmentedControl';
import { TextField } from '../ui/TextField';
import styles from './AuthDialog.module.css';

export type AuthMode = 'login' | 'register';

export type AuthDialogProps = {
  open: boolean;
  initialMode: AuthMode;
  onClose: () => void;
  onSuccess?: () => void;
};

type FieldErrors = {
  username?: string;
  email?: string;
  password?: string;
  confirm?: string;
  terms?: string;
};

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * 注册 409 的 detail 会说明是用户名还是邮箱冲突；两样都提到（唯一索引竞态）时
 * 落到表单级错误，不猜是哪一个字段。
 */
function conflictField(detail: string): 'username' | 'email' | null {
  const username = detail.includes('用户名');
  const email = detail.includes('邮箱');
  if (username && !email) return 'username';
  if (email && !username) return 'email';
  return null;
}

/**
 * 登录 / 注册弹层：手机贴底 Sheet（最高 88dvh），桌面居中 420px。
 * 复用 ui/Dialog 的焦点陷阱与滚动锁。
 */
export function AuthDialog({ open, initialMode, onClose, onSuccess }: AuthDialogProps) {
  const { login, register } = useSession();
  const { toast } = useToast();
  const { navigate } = useHashRoute();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [accepted, setAccepted] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);
  const usernameRef = useRef<HTMLInputElement | null>(null);
  const formId = 'auth-' + useId().replace(/[^a-zA-Z0-9_-]/g, '');

  useEffect(() => {
    setErrors({});
    setFormError('');
    setPassword('');
    setConfirm('');
    if (open) setMode(initialMode);
  }, [open, initialMode]);

  function switchMode(next: AuthMode) {
    if (next === mode) return;
    setMode(next);
    setErrors({});
    setFormError('');
    // 切换模式只清空密码，用户名保留，避免用户重填。
    setPassword('');
    setConfirm('');
  }

  function clearError(key: keyof FieldErrors) {
    setErrors(current => (current[key] ? { ...current, [key]: undefined } : current));
    if (formError) setFormError('');
  }

  function validate(): boolean {
    const next: FieldErrors = {};
    const name = username.trim();
    if (!name) next.username = '请输入用户名。';

    if (mode === 'login') {
      if (!password) next.password = '请输入密码。';
    } else {
      const mail = email.trim();
      if (mail && !EMAIL_PATTERN.test(mail)) next.email = '邮箱格式不太对，请再检查。';
      if (password.length < 8) next.password = '密码至少 8 位。';
      if (confirm !== password) next.confirm = '两次输入的密码不一致。';
      if (!accepted) next.terms = '请先阅读并同意服务条款和隐私政策。';
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !validate()) return;
    setBusy(true);
    setFormError('');
    try {
      if (mode === 'login') {
        await login(username.trim(), password);
      } else {
        const result = await register({
          username: username.trim(),
          password,
          email: email.trim(),
          accept_terms: accepted,
        });
        onSuccess?.();
        onClose();
        if (email.trim()) {
          if (!result.emailSent) {
            // 账号已经创建，只是这封验证邮件没发出去；不能让用户以为邮箱验证已生效。
            toast('账号已创建。当前环境未配置邮件服务，验证邮件没有发出。');
          }
        } else {
          toast('账号已创建。可在账户设置里绑定邮箱，用于找回密码。');
        }
        return;
      }
      onSuccess?.();
      onClose();
    } catch (error) {
      if (error instanceof ApiError) {
        if (mode === 'register' && error.status === 409) {
          const field = conflictField(error.message);
          if (field) {
            setErrors(current => ({ ...current, [field]: error.message }));
          } else {
            setFormError(error.message || '注册失败，请稍后再试。');
          }
        } else {
          // 422 的 message 已由 api.ts 的 detailText 转成字段提示。
          setFormError(error.message || '提交失败，请稍后再试。');
        }
      } else {
        setFormError(message(error));
      }
    } finally {
      setBusy(false);
    }
  }

  function openForgot() {
    onClose();
    navigate('/forgot');
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={mode === 'login' ? '登录行迹' : '创建账号'}
      busy={busy}
      className={styles.dialog}
      initialFocusRef={usernameRef}
      footer={
        <div className={styles.actions}>
          <Button type="submit" form={formId} loading={busy} className={styles.submit}>
            {mode === 'login' ? '登录' : '注册'}
          </Button>
        </div>
      }
    >
      <form id={formId} className={styles.form} onSubmit={handleSubmit} noValidate>
        <SegmentedControl
          label="登录或注册"
          value={mode}
          onChange={switchMode}
          options={[
            { value: 'login', label: '登录' },
            { value: 'register', label: '注册' },
          ]}
        />

        <TextField
          label="用户名"
          autoComplete="username"
          inputRef={usernameRef}
          value={username}
          error={errors.username}
          onChange={event => {
            setUsername(event.target.value);
            clearError('username');
          }}
        />

        {mode === 'register' ? (
          <TextField
            label="邮箱"
            type="email"
            inputMode="email"
            autoComplete="email"
            hint="选填。填写后可用于验证账号和找回密码，不会显示在公开分享里。"
            value={email}
            error={errors.email}
            onChange={event => {
              setEmail(event.target.value);
              clearError('email');
            }}
          />
        ) : null}

        <PasswordField
          label="密码"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          hint={mode === 'register' ? '至少 8 位。' : undefined}
          value={password}
          error={errors.password}
          onChange={event => {
            setPassword(event.target.value);
            clearError('password');
          }}
        />

        {mode === 'register' ? (
          <PasswordField
            label="确认密码"
            autoComplete="new-password"
            value={confirm}
            error={errors.confirm}
            onChange={event => {
              setConfirm(event.target.value);
              clearError('confirm');
            }}
          />
        ) : null}

        {mode === 'login' ? (
          <button type="button" className={styles.forgot} onClick={openForgot}>
            忘记密码？
          </button>
        ) : (
          <>
            <Checkbox
              label={
                <>
                  我已阅读并同意{' '}
                  <a href="#/terms?from=explore" target="_blank" rel="noreferrer">
                    《服务条款》
                  </a>{' '}
                  和{' '}
                  <a href="#/privacy?from=explore" target="_blank" rel="noreferrer">
                    《隐私政策》
                  </a>
                </>
              }
              checked={accepted}
              onChange={event => {
                setAccepted(event.target.checked);
                clearError('terms');
              }}
            />
            {errors.terms ? (
              <p className={styles.fieldError} role="alert">
                {errors.terms}
              </p>
            ) : null}
          </>
        )}

        {formError ? (
          <p className={styles.formError} role="alert">
            {formError}
          </p>
        ) : null}
        <p className={styles.srOnly} role="status" aria-live="polite">
          {Object.values(errors).filter(Boolean).join(' ')}
        </p>
      </form>
    </Dialog>
  );
}
