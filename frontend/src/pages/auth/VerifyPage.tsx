import { useEffect, useRef, useState } from 'react';
import { useSession } from '../../app/providers/SessionProvider';
import { useToast } from '../../app/providers/ToastProvider';
import { useHashRoute } from '../../app/routing/useHashRoute';
import { ApiError, message, resendEmail, verifyEmail } from '../../lib/api';
import { openAuth } from '../../lib/auth-events';
import { AlertIcon, CheckIcon } from '../../components/icons';
import { Button } from '../../components/ui/Button';
import { Kicker } from '../../components/ui/Kicker';
import { Spinner } from '../../components/ui/Spinner';
import styles from './auth.module.css';

type VerifyState = 'loading' | 'success' | 'error';

export function VerifyPage({ token }: { token: string }) {
  const { user, refresh } = useSession();
  const { navigate } = useHashRoute();
  const { toast } = useToast();
  const started = useRef(false);
  const synced = useRef(false);

  const [state, setState] = useState<VerifyState>(token ? 'loading' : 'error');
  const [email, setEmail] = useState('');
  const [error, setError] = useState(token ? '' : '链接无效或已过期');
  const [resendBusy, setResendBusy] = useState(false);
  const [resendError, setResendError] = useState('');

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    let active = true;
    verifyEmail(token)
      .then(result => {
        if (!active) return;
        setEmail(result?.email || '');
        setState('success');
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setError(
          cause instanceof ApiError && cause.status === 400
            ? '链接无效或已过期'
            : message(cause),
        );
        setState('error');
      });
    return () => {
      active = false;
    };
  }, [token]);

  // 验证成功后刷新会话，让「我的」立刻显示已验证；顺带清掉账户设置缓存的
  // 同邮箱「待验证」记录（验证的是别的地址时保留）。
  useEffect(() => {
    if (state !== 'success' || !user || synced.current) return;
    synced.current = true;
    try {
      const key = 'xingji-pending-email:' + user.username;
      const stored = window.localStorage.getItem(key);
      if (stored && (!email || stored.trim().toLowerCase() === email.trim().toLowerCase())) {
        window.localStorage.removeItem(key);
      }
    } catch {
      // 存储不可用时忽略。
    }
    void refresh();
  }, [state, user, email, refresh]);

  function goMine() {
    if (user) {
      navigate('/profile');
    } else {
      navigate('/explore');
      openAuth('login');
    }
  }

  async function handleResend() {
    if (resendBusy) return;
    if (!user) {
      openAuth('login');
      return;
    }
    setResendBusy(true);
    setResendError('');
    try {
      await resendEmail();
      toast('验证邮件已发送，请查收', 'success');
    } catch (cause) {
      setResendError(message(cause));
    } finally {
      setResendBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <button type="button" className={styles.back} onClick={() => navigate('/explore')}>
            返回首页
          </button>
          <Kicker className={styles.kicker}>VERIFY</Kicker>
        </div>

        {state === 'loading' ? (
          <div className={styles.statusBox} role="status" aria-live="polite">
            <Spinner label="正在验证邮箱" />
            <h1 className={styles.statusTitle}>正在验证邮箱</h1>
            <p className={styles.statusBody}>请稍候，这通常只需要几秒。</p>
          </div>
        ) : null}

        {state === 'success' ? (
          <div className={styles.statusBox} role="status">
            <span className={styles.statusIcon} data-tone="success">
              <CheckIcon size={22} />
            </span>
            <h1 className={styles.statusTitle}>邮箱已验证</h1>
            <p className={styles.statusBody}>
              {email ? email + ' 已绑定到你的行迹账号。' : '你的邮箱已绑定到行迹账号。'}
              之后可以用邮箱找回密码。
            </p>
            <Button onClick={goMine} className={styles.submit}>
              {user ? '去我的' : '去首页登录'}
            </Button>
            <button type="button" className={styles.inlineLink} onClick={() => navigate('/explore')}>
              返回首页
            </button>
          </div>
        ) : null}

        {state === 'error' ? (
          <div className={styles.statusBox} role="alert">
            <span className={styles.statusIcon} data-tone="danger">
              <AlertIcon size={22} />
            </span>
            <h1 className={styles.statusTitle}>验证失败</h1>
            <p className={styles.statusBody}>{error || '链接无效或已过期'}</p>
            <p className={styles.meta}>
              {user
                ? '可以重新发送一封验证邮件。'
                : '重新发送需要先登录账号。'}
            </p>
            {resendError ? (
              <p className={styles.formError} role="alert">
                {resendError}
              </p>
            ) : null}
            <Button onClick={() => void handleResend()} loading={resendBusy} className={styles.submit}>
              重新发送验证邮件
            </Button>
            <button type="button" className={styles.inlineLink} onClick={() => navigate('/explore')}>
              返回首页
            </button>
          </div>
        ) : null}
      </div>
    </main>
  );
}
