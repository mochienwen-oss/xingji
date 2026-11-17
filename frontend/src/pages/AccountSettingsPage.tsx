import { useEffect, useId, useState, type FormEvent } from 'react';
import { useSession } from '../app/providers/SessionProvider';
import { useToast } from '../app/providers/ToastProvider';
import { useHashRoute } from '../app/routing/useHashRoute';
import {
  acceptTerms,
  ApiError,
  changeEmail,
  changePassword,
  dateText,
  deleteAccount,
  getMemoryPreference,
  message,
  resendEmail,
  setMemoryPreference,
} from '../lib/api';
import { openAuth } from '../lib/auth-events';
import { clearXingjiStorage } from '../lib/storage';
import { FeedbackButton, useSupportEmail } from '../components/Feedback';
import { BackIcon } from '../components/icons';
import { Button } from '../components/ui/Button';
import { Checkbox } from '../components/ui/Checkbox';
import { EmptyState } from '../components/ui/EmptyState';
import { Kicker } from '../components/ui/Kicker';
import { PasswordField } from '../components/ui/PasswordField';
import { Skeleton } from '../components/ui/Skeleton';
import { TextField } from '../components/ui/TextField';
import styles from './AccountSettingsPage.module.css';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PENDING_EMAIL_PREFIX = 'xingji-pending-email:';

function pendingEmailKey(username: string): string {
  return PENDING_EMAIL_PREFIX + username;
}

function readPendingEmail(username: string): string {
  try {
    return window.localStorage.getItem(pendingEmailKey(username)) || '';
  } catch {
    return '';
  }
}

function writePendingEmail(username: string, email: string | null): void {
  try {
    const key = pendingEmailKey(username);
    if (email) window.localStorage.setItem(key, email);
    else window.localStorage.removeItem(key);
  } catch {
    // 存储不可用（隐私模式 / 配额满）时，本页内存里的「待验证」仍然生效。
  }
}

type EmailErrors = { email?: string; password?: string };
type PasswordErrors = { current?: string; next?: string; confirm?: string };

export function AccountSettingsPage() {
  const { user, loading, refresh, logout } = useSession();
  const { navigate } = useHashRoute();
  const { toast } = useToast();
  const supportEmail = useSupportEmail();

  const [emailOpen, setEmailOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [emailErrors, setEmailErrors] = useState<EmailErrors>({});
  const [emailFormError, setEmailFormError] = useState('');
  const [emailBusy, setEmailBusy] = useState(false);
  const [pendingEmail, setPendingEmail] = useState('');
  const [resendIn, setResendIn] = useState(0);
  const [resendBusy, setResendBusy] = useState(false);
  const [resendError, setResendError] = useState('');

  const [passwordOpen, setPasswordOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordErrors, setPasswordErrors] = useState<PasswordErrors>({});
  const [passwordFormError, setPasswordFormError] = useState('');
  const [passwordBusy, setPasswordBusy] = useState(false);
  const passwordPanelId = useId();

  const [termsBusy, setTermsBusy] = useState(false);
  const [termsError, setTermsError] = useState('');

  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryError, setMemoryError] = useState('');

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const deletePanelId = useId();

  useEffect(() => {
    if (user && !user.email) setEmailOpen(true);
  }, [user]);

  // 待验证邮箱只放 state 会随刷新丢掉：按用户名存进 localStorage 并在挂载时读回。
  // 新邮箱验证通过后 /me 的 email 会变成它，此时清掉缓存。
  useEffect(() => {
    if (!user) return;
    const stored = readPendingEmail(user.username);
    const verifiedCurrent = Boolean(
      stored
      && user.emailVerified
      && user.email?.trim().toLowerCase() === stored.trim().toLowerCase(),
    );
    if (verifiedCurrent) {
      writePendingEmail(user.username, null);
      setPendingEmail('');
      return;
    }
    if (stored) setPendingEmail(stored);
  }, [user]);

  // 记忆开关以服务端为准；读取失败时按默认开启显示，勾选仍可保存。
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setMemoryError('');
    getMemoryPreference()
      .then(result => {
        if (!cancelled) setMemoryEnabled(result.enabled);
      })
      .catch(() => {
        // 离线或接口暂时不可用时保持默认值，不阻塞账户页其它操作。
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = window.setTimeout(() => setResendIn(value => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [resendIn]);

  if (loading) {
    return (
      <main className={styles.page}>
        <div className={styles.shell} role="status" aria-live="polite">
          <div className={styles.topbar}>
            <span className={styles.backPlaceholder} />
          </div>
          <Skeleton className={styles.skeletonTitle} />
          <Skeleton className={styles.skeletonCard} />
          <Skeleton className={styles.skeletonCard} />
          <p className={styles.loadingText}>正在读取账户设置…</p>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className={styles.page}>
        <div className={styles.shell}>
          <div className={styles.topbar}>
            <button type="button" className={styles.back} onClick={() => navigate('/profile')}>
              <BackIcon size={18} />
              返回我的
            </button>
            <Kicker className={styles.kicker}>ACCOUNT</Kicker>
          </div>
          <h1 className={styles.title}>账户设置</h1>
          <EmptyState
            title="请先登录"
            body="登录后才能管理邮箱、密码与注销，游客的草稿仍留在这台设备上。"
            action={<Button onClick={() => openAuth('login')}>登录 / 注册</Button>}
          />
        </div>
      </main>
    );
  }

  const emailState = pendingEmail ? '待验证' : !user.email ? '未绑定' : user.emailVerified ? '已验证' : '待验证';
  const emailStateKey = pendingEmail ? 'pending' : !user.email ? 'missing' : user.emailVerified ? 'verified' : 'pending';
  const needsVerification = Boolean(pendingEmail || (user.email && !user.emailVerified));

  function clearEmailError(key: keyof EmailErrors) {
    setEmailErrors(current => (current[key] ? { ...current, [key]: undefined } : current));
    if (emailFormError) setEmailFormError('');
  }

  async function handleChangeEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (emailBusy || !user) return;
    const next: EmailErrors = {};
    const mail = email.trim();
    if (!mail) next.email = '请输入新邮箱。';
    else if (!EMAIL_PATTERN.test(mail)) next.email = '邮箱格式不太对，请再检查。';
    if (!emailPassword) next.password = '请输入当前密码。';
    setEmailErrors(next);
    if (Object.keys(next).length > 0) return;

    setEmailBusy(true);
    setEmailFormError('');
    try {
      const result = await changeEmail({ email: mail, password: emailPassword });
      // 正常响应带 pending_email；若只回 email 也认，都没有就用刚提交的地址。
      const returned = result as { pending_email?: string | null; email?: string | null };
      const nextPending = returned.pending_email?.trim() || returned.email?.trim() || mail;
      setPendingEmail(nextPending);
      writePendingEmail(user.username, nextPending);
      setResendIn(60);
      setEmail('');
      setEmailPassword('');
      setEmailOpen(false);
      toast(
        result.email_sent ? '验证邮件已发送到新邮箱' : '邮箱待验证，请稍后重新发送验证邮件',
        result.email_sent ? 'success' : 'info',
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setEmailErrors(current => ({ ...current, password: error.message || '密码错误。' }));
      } else if (error instanceof ApiError && error.status === 409) {
        setEmailErrors(current => ({ ...current, email: error.message }));
      } else {
        setEmailFormError(message(error));
      }
    } finally {
      setEmailBusy(false);
    }
  }

  async function handleResend() {
    if (resendBusy || resendIn > 0 || !user) return;
    setResendBusy(true);
    setResendError('');
    try {
      const result = await resendEmail();
      if (result.pending_email) {
        setPendingEmail(result.pending_email);
        writePendingEmail(user.username, result.pending_email);
      }
      setResendIn(60);
      toast('验证邮件已发送，请查收', 'success');
    } catch (error) {
      setResendError(message(error));
      if (error instanceof ApiError && error.status === 409) {
        // 服务器认为邮箱已经验证；刷新一次，让状态与后台一致。
        await refresh();
      }
    } finally {
      setResendBusy(false);
    }
  }

  function clearPasswordError(key: keyof PasswordErrors) {
    setPasswordErrors(current => (current[key] ? { ...current, [key]: undefined } : current));
    if (passwordFormError) setPasswordFormError('');
  }

  async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwordBusy) return;
    const next: PasswordErrors = {};
    if (!currentPassword) next.current = '请输入当前密码。';
    if (newPassword.length < 8) next.next = '新密码至少 8 位。';
    if (confirmPassword !== newPassword) next.confirm = '两次输入的新密码不一致。';
    setPasswordErrors(next);
    if (Object.keys(next).length > 0) return;

    setPasswordBusy(true);
    setPasswordFormError('');
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setPasswordErrors({});
      setPasswordFormError('');
      setPasswordOpen(false);
      toast('密码已更新，其他设备需重新登录', 'success');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setPasswordErrors(current => ({ ...current, current: error.message || '当前密码错误。' }));
      } else {
        setPasswordFormError(message(error));
      }
    } finally {
      setPasswordBusy(false);
    }
  }

  async function handleAcceptTerms() {
    setTermsBusy(true);
    setTermsError('');
    try {
      await acceptTerms();
      await refresh();
      toast('已接受最新服务条款', 'success');
    } catch (error) {
      setTermsError(message(error));
    } finally {
      setTermsBusy(false);
    }
  }

  async function handleMemoryToggle(enabled: boolean) {
    if (memoryBusy) return;
    const previous = memoryEnabled;
    setMemoryEnabled(enabled);
    setMemoryBusy(true);
    setMemoryError('');
    try {
      const result = await setMemoryPreference(enabled);
      setMemoryEnabled(result.enabled);
      toast(result.enabled ? 'AI 会记住你的旅行偏好' : 'AI 已停止记录旅行偏好', 'success');
    } catch (error) {
      setMemoryEnabled(previous);
      setMemoryError(message(error));
    } finally {
      setMemoryBusy(false);
    }
  }

  async function handleDelete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (deleteBusy || !deletePassword || deleteConfirm !== '注销') return;
    setDeleteBusy(true);
    setDeleteError('');
    try {
      await deleteAccount({ password: deletePassword, confirm: '注销' });
      clearXingjiStorage();
      await logout();
      toast('账号已注销', 'success');
      navigate('/explore', { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setDeleteError(error.message || '密码错误。');
      } else {
        setDeleteError(message(error));
      }
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <button type="button" className={styles.back} onClick={() => navigate('/profile')}>
            <BackIcon size={18} />
            返回我的
          </button>
          <Kicker className={styles.kicker}>ACCOUNT</Kicker>
        </div>

        <header className={styles.intro}>
          <h1 className={styles.title}>账户设置</h1>
          <p className={styles.lede}>管理登录邮箱、密码和条款，或注销账号。</p>
        </header>

        <section className={styles.card} aria-labelledby="email-title">
          <div className={styles.cardHead}>
            <h2 id="email-title" className={styles.cardTitle}>
              邮箱
            </h2>
            <span className={styles.state} data-state={emailStateKey}>
              {emailState}
            </span>
          </div>

          <div className={styles.emailCurrent}>
            <span className={styles.fieldLabel}>当前邮箱</span>
            <span className={styles.emailValue}>{user.email || '未绑定邮箱'}</span>
          </div>

          {pendingEmail ? (
            <div className={styles.pending} role="status">
              <strong className={styles.pendingLabel}>待验证：</strong>
              <span className={styles.pendingEmail}>{pendingEmail}</span>
              <p>
                {user.email
                  ? '验证完成前，当前邮箱仍然有效；验证链接会发到新邮箱。'
                  : '验证完成前，账号还没有可用于找回密码的邮箱。'}
              </p>
            </div>
          ) : null}

          {needsVerification ? (
            <div className={styles.resendRow}>
              <Button
                variant="secondary"
                onClick={() => void handleResend()}
                loading={resendBusy}
                disabled={resendIn > 0}
              >
                {resendIn > 0 ? resendIn + ' 秒后可重新发送' : '重新发送验证邮件'}
              </Button>
              {resendError ? (
                <p className={styles.formError} role="alert">
                  {resendError}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className={styles.cardActions}>
            <Button variant="secondary" onClick={() => setEmailOpen(open => !open)} aria-expanded={emailOpen}>
              {user.email ? '修改邮箱' : '绑定邮箱'}
            </Button>
            {emailOpen ? (
              <Button variant="text" onClick={() => setEmailOpen(false)}>
                取消
              </Button>
            ) : null}
          </div>

          {emailOpen ? (
            <form className={styles.form} onSubmit={handleChangeEmail} noValidate>
              <p className={styles.note}>
                修改邮箱需要验证当前密码。新邮箱验证完成前，旧邮箱不会被替换。
              </p>
              <TextField
                label="新邮箱"
                type="email"
                inputMode="email"
                autoComplete="email"
                value={email}
                error={emailErrors.email}
                onChange={event => {
                  setEmail(event.target.value);
                  clearEmailError('email');
                }}
              />
              <PasswordField
                label="当前密码"
                autoComplete="current-password"
                value={emailPassword}
                error={emailErrors.password}
                onChange={event => {
                  setEmailPassword(event.target.value);
                  clearEmailError('password');
                }}
              />
              {emailFormError ? (
                <p className={styles.formError} role="alert">
                  {emailFormError}
                </p>
              ) : null}
              <p className={styles.srOnly} role="status" aria-live="polite">
                {Object.values(emailErrors).filter(Boolean).join(' ')}
              </p>
              <Button type="submit" loading={emailBusy} className={styles.submit}>
                发送验证邮件
              </Button>
            </form>
          ) : null}
        </section>

        <section className={styles.card} aria-labelledby="password-title">
          <div className={styles.cardHead}>
            <h2 id="password-title" className={styles.cardTitle}>
              密码
            </h2>
          </div>
          <div className={styles.cardActions}>
            <Button
              variant="secondary"
              onClick={() => setPasswordOpen(open => !open)}
              aria-expanded={passwordOpen}
              aria-controls={passwordPanelId}
            >
              {passwordOpen ? '收起修改密码' : '修改密码'}
            </Button>
            {passwordOpen ? (
              <Button variant="text" onClick={() => setPasswordOpen(false)}>
                取消
              </Button>
            ) : null}
          </div>
          {passwordOpen ? (
            <form id={passwordPanelId} className={styles.form} onSubmit={handleChangePassword} noValidate>
              <p className={styles.note}>修改密码会让其他设备退出，当前设备保持登录。</p>
              <PasswordField
                label="当前密码"
                autoComplete="current-password"
                autoFocus
                value={currentPassword}
                error={passwordErrors.current}
                onChange={event => {
                  setCurrentPassword(event.target.value);
                  clearPasswordError('current');
                }}
              />
              <PasswordField
                label="新密码"
                autoComplete="new-password"
                hint="至少 8 位，建议使用长一些的密码。"
                value={newPassword}
                error={passwordErrors.next}
                onChange={event => {
                  setNewPassword(event.target.value);
                  clearPasswordError('next');
                }}
              />
              <PasswordField
                label="确认新密码"
                autoComplete="new-password"
                value={confirmPassword}
                error={passwordErrors.confirm}
                onChange={event => {
                  setConfirmPassword(event.target.value);
                  clearPasswordError('confirm');
                }}
              />
              {passwordFormError ? (
                <p className={styles.formError} role="alert">
                  {passwordFormError}
                </p>
              ) : null}
              <p className={styles.srOnly} role="status" aria-live="polite">
                {Object.values(passwordErrors).filter(Boolean).join(' ')}
              </p>
              <Button type="submit" loading={passwordBusy} className={styles.submit}>
                更新密码
              </Button>
            </form>
          ) : null}
        </section>

        <section className={styles.card} aria-labelledby="memory-title">
          <div className={styles.cardHead}>
            <h2 id="memory-title" className={styles.cardTitle}>
              AI 记忆
            </h2>
            <span className={styles.state} data-state={memoryEnabled ? 'verified' : 'pending'}>
              {memoryEnabled ? '已开启' : '已关闭'}
            </span>
          </div>
          <p className={styles.note}>
            开启后，AI 会在对话中记住你的节奏、兴趣和忌讳，下次规划直接用上。只保存旅行偏好，不保存密码等敏感信息；随时可以关闭。
          </p>
          <Checkbox
            containerClassName={styles.memoryRow}
            label="让 AI 记住我的旅行偏好"
            hint={memoryEnabled ? '关闭后不再读取或写入长期记忆。' : '当前不读取也不写入长期记忆。'}
            checked={memoryEnabled}
            disabled={memoryBusy}
            onChange={event => void handleMemoryToggle(event.target.checked)}
          />
          <p className={styles.srOnly} role="status" aria-live="polite">
            {memoryBusy ? '正在保存记忆设置…' : ''}
          </p>
          {memoryError ? (
            <p className={styles.formError} role="alert">
              {memoryError}
            </p>
          ) : null}
        </section>

        <section className={styles.card} aria-labelledby="terms-title">
          <div className={styles.cardHead}>
            <h2 id="terms-title" className={styles.cardTitle}>
              服务条款
            </h2>
            <span className={styles.state} data-state={user.acceptedTermsAt ? 'verified' : 'pending'}>
              {user.acceptedTermsAt ? '已接受' : '待同意'}
            </span>
          </div>
          <p className={styles.note}>
            {user.acceptedTermsAt
              ? '上次接受时间：' + dateText(user.acceptedTermsAt) + '。'
              : '尚未接受服务条款。'}
            {user.needsTerms ? ' 条款有更新，请查看后同意。' : ''}
          </p>
          <div className={styles.cardActions}>
            <Button variant="secondary" onClick={() => navigate('/terms?from=account')}>
              查看服务条款
            </Button>
            <Button variant="text" onClick={() => navigate('/privacy?from=account')}>
              查看隐私政策
            </Button>
          </div>
          {!user.acceptedTermsAt || user.needsTerms ? (
            <Button onClick={() => void handleAcceptTerms()} loading={termsBusy} className={styles.submit}>
              同意服务条款
            </Button>
          ) : null}
          {termsError ? (
            <p className={styles.formError} role="alert">
              {termsError}
            </p>
          ) : null}
        </section>

        {supportEmail ? (
          <section className={styles.card} aria-labelledby="help-title">
            <div className={styles.cardHead}>
              <h2 id="help-title" className={styles.cardTitle}>
                帮助与反馈
              </h2>
            </div>
            <p className={styles.note}>
              遇到问题、发现行程内容有误，或想提建议，可以发邮件给我们。邮件会自动带上版本号、当前页面与浏览器信息，方便定位。
            </p>
            <div className={styles.cardActions}>
              <FeedbackButton label="写反馈邮件" username={user.username} />
            </div>
            <p className={styles.note}>也可以直接发到 {supportEmail}。</p>
          </section>
        ) : null}

        <section className={styles.card} aria-labelledby="export-title">
          <div className={styles.cardHead}>
            <h2 id="export-title" className={styles.cardTitle}>
              我的数据
            </h2>
            <span className={styles.state} data-state="verified">可导出</span>
          </div>
          <p className={styles.note}>
            导出账号资料、全部行程（含已删除）、预算花费与 AI 记忆，格式为 JSON。文件由浏览器直接下载，不会发送到其他地方。
          </p>
          <div className={styles.cardActions}>
            <Button
              variant="secondary"
              onClick={() => {
                window.location.assign('/api/account/export');
              }}
            >
              导出我的数据
            </Button>
          </div>
          <p className={styles.note}>导出内容不含密码、登录令牌或分享令牌。</p>
        </section>

        <section className={styles.card + ' ' + styles.dangerZone} aria-labelledby="danger-title">
          <div className={styles.cardHead}>
            <h2 id="danger-title" className={styles.cardTitle}>
              注销账号
            </h2>
            <span className={styles.dangerTag}>不可恢复</span>
          </div>
          <p className={styles.dangerCopy}>
            注销会永久删除账号、账号下的行程、协作与分享链接、预算与花费记录，且无法恢复。
          </p>
          <Button
            variant="secondary"
            onClick={() => setDeleteOpen(open => !open)}
            aria-expanded={deleteOpen}
            aria-controls={deletePanelId}
          >
            {deleteOpen ? '收起注销' : '继续注销'}
          </Button>

          {deleteOpen ? (
            <form id={deletePanelId} className={styles.form} onSubmit={handleDelete} noValidate>
              <p className={styles.note}>请输入当前密码，并输入「注销」以确认。此操作不可撤销。</p>
              <PasswordField
                label="当前密码"
                autoComplete="current-password"
                value={deletePassword}
                onChange={event => setDeletePassword(event.target.value)}
              />
              <TextField
                label="输入「注销」以确认"
                autoComplete="off"
                value={deleteConfirm}
                onChange={event => setDeleteConfirm(event.target.value)}
                hint="必须与「注销」完全一致，删除按钮才会启用。"
              />
              {deleteError ? (
                <p className={styles.formError} role="alert">
                  {deleteError}
                </p>
              ) : null}
              <Button
                type="submit"
                variant="danger"
                loading={deleteBusy}
                disabled={!deletePassword || deleteConfirm !== '注销'}
                className={styles.submit}
              >
                永久注销账号
              </Button>
            </form>
          ) : null}
        </section>
      </div>
    </main>
  );
}
