import { useEffect, useState, type FormEvent } from 'react';
import { useHashRoute } from '../../app/routing/useHashRoute';
import { forgotPassword } from '../../lib/api';
import { openAuth } from '../../lib/auth-events';
import { BackIcon } from '../../components/icons';
import { Button } from '../../components/ui/Button';
import { Kicker } from '../../components/ui/Kicker';
import { TextField } from '../../components/ui/TextField';
import styles from './auth.module.css';

const UNIFIED_MESSAGE = '如果账号存在，我们已发送重置链接';

export function ForgotPage() {
  const { navigate } = useHashRoute();
  const [identifier, setIdentifier] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setTimeout(() => setCountdown(value => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  async function send() {
    setBusy(true);
    try {
      await forgotPassword(identifier.trim());
    } catch {
      // 后端对未知账号也返回成功；这里同样不暴露账号是否存在。
    } finally {
      setBusy(false);
      setSent(true);
      setCountdown(60);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || (sent && countdown > 0)) return;
    const value = identifier.trim();
    if (!value) {
      setFieldError('请输入用户名或邮箱。');
      return;
    }
    setFieldError('');
    void send();
  }

  function goLogin() {
    navigate('/explore');
    openAuth('login');
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <button type="button" className={styles.back} onClick={goLogin}>
            <BackIcon size={18} />
            返回
          </button>
          <Kicker className={styles.kicker}>RECOVER</Kicker>
        </div>

        <header className={styles.header}>
          <h1 className={styles.title}>忘记密码</h1>
          <p className={styles.lede}>输入注册时的用户名或邮箱，我们会发送一封重置密码的邮件。</p>
        </header>

        <section className={styles.card} aria-labelledby="forgot-form-title">
          <h2 id="forgot-form-title" className={styles.cardTitle}>
            找回账号
          </h2>
          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <TextField
              label="用户名或邮箱"
              autoComplete="username"
              value={identifier}
              error={fieldError}
              hint="两者填其一即可，不区分大小写。"
              onChange={event => {
                setIdentifier(event.target.value);
                if (fieldError) setFieldError('');
              }}
            />
            {sent ? (
              <div className={styles.notice} role="status">
                <p>{UNIFIED_MESSAGE}</p>
                <p className={styles.noticeSub}>
                  没收到？请检查垃圾邮件，或在倒计时结束后重试。链接 30 分钟内有效。
                </p>
              </div>
            ) : null}
            <Button
              type="submit"
              className={styles.submit}
              loading={busy}
              disabled={sent && countdown > 0}
            >
              {sent && countdown > 0
                ? countdown + ' 秒后可重新发送'
                : sent
                  ? '重新发送'
                  : '发送重置链接'}
            </Button>
          </form>
        </section>

        <button type="button" className={styles.inlineLink} onClick={goLogin}>
          返回登录
        </button>

        <p className={styles.meta}>
          为保护账号安全，无论邮箱是否存在，提示都相同。
        </p>
      </div>
    </main>
  );
}
