import { useState, type FormEvent } from 'react';
import { useSession } from '../../app/providers/SessionProvider';
import { useToast } from '../../app/providers/ToastProvider';
import { useHashRoute } from '../../app/routing/useHashRoute';
import { ApiError, message, resetPassword } from '../../lib/api';
import { clearXingjiStorage } from '../../lib/storage';
import { AlertIcon, BackIcon } from '../../components/icons';
import { Button } from '../../components/ui/Button';
import { Kicker } from '../../components/ui/Kicker';
import { PasswordField } from '../../components/ui/PasswordField';
import styles from './auth.module.css';

export function ResetPage({ token }: { token: string }) {
  const { logout } = useSession();
  const { navigate } = useHashRoute();
  const { toast } = useToast();

  const [invalid, setInvalid] = useState(!token);
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ next?: string; confirm?: string }>({});
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || invalid) return;
    const next: { next?: string; confirm?: string } = {};
    if (newPassword.length < 8) next.next = '新密码至少 8 位。';
    if (confirm !== newPassword) next.confirm = '两次输入的密码不一致。';
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setBusy(true);
    setFormError('');
    try {
      await resetPassword({ token, new_password: newPassword });
      clearXingjiStorage();
      await logout();
      toast('密码已更新，请用新密码登录', 'success');
      navigate('/explore', { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        setInvalid(true);
      } else {
        setFormError(message(error));
      }
    } finally {
      setBusy(false);
    }
  }

  if (invalid) {
    return (
      <main className={styles.page}>
        <div className={styles.shell}>
          <div className={styles.topbar}>
            <button type="button" className={styles.back} onClick={() => navigate('/explore')}>
              <BackIcon size={18} />
              返回首页
            </button>
            <Kicker className={styles.kicker}>RESET</Kicker>
          </div>
          <div className={styles.statusBox} role="alert">
            <span className={styles.statusIcon} data-tone="danger">
              <AlertIcon size={22} />
            </span>
            <h1 className={styles.statusTitle}>链接无效或已过期</h1>
            <p className={styles.statusBody}>
              重置链接只能使用一次，且会在 30 分钟后失效。请重新申请一封邮件。
            </p>
            <Button onClick={() => navigate('/forgot')} className={styles.submit}>
              重新申请
            </Button>
            <button type="button" className={styles.inlineLink} onClick={() => navigate('/explore')}>
              先回首页看看
            </button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <button type="button" className={styles.back} onClick={() => navigate('/explore')}>
            <BackIcon size={18} />
            返回首页
          </button>
          <Kicker className={styles.kicker}>RESET</Kicker>
        </div>

        <header className={styles.header}>
          <h1 className={styles.title}>设置新密码</h1>
          <p className={styles.lede}>设置后，其他设备上的登录会失效，请用新密码重新登录。</p>
        </header>

        <section className={styles.card} aria-labelledby="reset-form-title">
          <h2 id="reset-form-title" className={styles.cardTitle}>
            新密码
          </h2>
          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <PasswordField
              label="新密码"
              autoComplete="new-password"
              hint="至少 8 位，建议混合字母与数字。"
              value={newPassword}
              error={errors.next}
              onChange={event => {
                setNewPassword(event.target.value);
                if (errors.next) setErrors(current => ({ ...current, next: undefined }));
              }}
            />
            <PasswordField
              label="确认新密码"
              autoComplete="new-password"
              value={confirm}
              error={errors.confirm}
              onChange={event => {
                setConfirm(event.target.value);
                if (errors.confirm) setErrors(current => ({ ...current, confirm: undefined }));
              }}
            />
            {formError ? (
              <p className={styles.formError} role="alert">
                {formError}
              </p>
            ) : null}
            <p className={styles.srOnly} role="status" aria-live="polite">
              {Object.values(errors).filter(Boolean).join(' ')}
            </p>
            <Button type="submit" className={styles.submit} loading={busy}>
              更新密码
            </Button>
          </form>
        </section>

        <p className={styles.meta}>链接仅可使用一次。提交成功后，这台设备也会退出登录。</p>
      </div>
    </main>
  );
}
