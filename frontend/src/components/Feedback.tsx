import { useEffect, useId, useState, type FormEvent } from 'react';
import { loadAppConfig } from '../lib/config';
import { APP_VERSION } from '../lib/appInfo';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';
import styles from './Feedback.module.css';

export const FEEDBACK_KINDS = ['使用问题', '行程内容有误', '功能建议', '账号与隐私', '其他'] as const;
export const FEEDBACK_MESSAGE_LIMIT = 1200;

export type FeedbackInput = {
  email: string;
  kind: string;
  message: string;
  contact?: string;
  page?: string;
  version?: string;
  userAgent?: string;
  username?: string;
};

/** 纯函数，方便测试：生成带版本、页面、浏览器信息的反馈邮件。 */
export function buildFeedbackMailto(input: FeedbackInput): string {
  const subject = '[行迹反馈] ' + input.kind + (input.username ? ' · ' + input.username : '');
  const body = [
    '类型：' + input.kind,
    '内容：',
    input.message.trim(),
    '',
    '联系方式：' + (input.contact?.trim() || '未填写'),
    '账号：' + (input.username || '未登录'),
    '版本：行迹 Trip ' + (input.version || APP_VERSION),
    '页面：' + (input.page || ''),
    '浏览器：' + (input.userAgent || ''),
  ].join('\n');
  return 'mailto:' + input.email.trim() + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
}

let cachedSupportEmail: string | null = null;
let supportEmailRequest: Promise<string> | null = null;

function fetchSupportEmail(): Promise<string> {
  if (supportEmailRequest) return supportEmailRequest;
  supportEmailRequest = loadAppConfig()
    .then(config => (config.support_email || '').trim())
    .catch(() => '');
  return supportEmailRequest;
}

/** 客服邮箱来自部署环境；未配置或格式不合法时为空，调用方据此隐藏入口。 */
export function useSupportEmail(): string {
  const [email, setEmail] = useState(cachedSupportEmail ?? '');
  useEffect(() => {
    if (cachedSupportEmail !== null) return;
    let alive = true;
    void fetchSupportEmail().then(value => {
      cachedSupportEmail = value;
      if (alive) setEmail(value);
    });
    return () => {
      alive = false;
    };
  }, []);
  return email;
}

type FeedbackDialogProps = {
  open: boolean;
  email: string;
  onClose: () => void;
  username?: string;
};

function FeedbackDialog({ open, email, onClose, username }: FeedbackDialogProps) {
  const [kind, setKind] = useState<string>(FEEDBACK_KINDS[0]);
  const [message, setMessage] = useState('');
  const [contact, setContact] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [copied, setCopied] = useState(false);
  const formId = useId();
  const kindId = useId();
  const messageId = useId();
  const contactId = useId();

  function close() {
    onClose();
    setKind(FEEDBACK_KINDS[0]);
    setMessage('');
    setContact('');
    setStatus('');
    setError('');
    setCopied(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (text.length < 4) {
      setError('请至少写 4 个字，方便我们定位问题。');
      return;
    }
    setError('');
    setStatus('');
    const href = buildFeedbackMailto({
      email,
      kind,
      message: text,
      contact,
      username,
      page: window.location.href,
      userAgent: window.navigator.userAgent,
    });
    window.location.href = href;
    setStatus('已打开邮件客户端，请确认发送。若没有反应，可以复制邮箱手动发送。');
  }

  async function copyEmail() {
    try {
      await window.navigator.clipboard.writeText(email);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('复制失败，请手动选中邮箱地址。');
    }
  }

  return (
    <Dialog open={open} onClose={close} title="帮助与反馈" footer={
      <>
        <Button variant="text" onClick={close}>取消</Button>
        <Button type="submit" form={formId} disabled={!message.trim()}>打开邮件客户端</Button>
      </>
    }>
      <form id={formId} className={styles.form} onSubmit={handleSubmit} noValidate>
        <p className={styles.intro}>
          反馈会从你的邮件客户端发出。为了定位问题，邮件里会自动带上当前版本、页面与浏览器信息。
        </p>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={kindId}>问题类型</label>
          <select id={kindId} className={styles.select} value={kind} onChange={event => setKind(event.target.value)}>
            {FEEDBACK_KINDS.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={messageId}>具体内容</label>
          <textarea
            id={messageId}
            className={styles.textarea}
            value={message}
            maxLength={FEEDBACK_MESSAGE_LIMIT}
            placeholder="例如：在杭州行程里把西湖拖到第二天后，保存提示冲突。"
            onChange={event => {
              setMessage(event.target.value);
              if (error) setError('');
            }}
          />
          <div className={styles.meta}>
            <span className={styles.hint}>至少 4 个字，不要填写密码等敏感信息。</span>
            <span className={styles.counter}>{message.length}/{FEEDBACK_MESSAGE_LIMIT}</span>
          </div>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={contactId}>联系方式（可选）</label>
          <input
            id={contactId}
            className={styles.input}
            value={contact}
            autoComplete="email"
            placeholder="邮箱或微信，方便我们回复"
            onChange={event => setContact(event.target.value)}
          />
        </div>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        {status ? <p className={styles.status} role="status">{status}</p> : null}
        <p className={styles.emailLine}>
          也可以直接发到 <a href={'mailto:' + email}>{email}</a>
          <Button variant="text" onClick={() => void copyEmail()}>{copied ? '已复制' : '复制邮箱'}</Button>
        </p>
      </form>
    </Dialog>
  );
}

type FeedbackButtonProps = {
  label?: string;
  variant?: 'primary' | 'secondary' | 'text';
  username?: string;
};

/** 只有部署时配置了 SUPPORT_EMAIL 才渲染，避免给用户一个发不出去的入口。 */
export function FeedbackButton({ label = '反馈问题', variant = 'secondary', username }: FeedbackButtonProps) {
  const email = useSupportEmail();
  const [open, setOpen] = useState(false);
  if (!email) return null;
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>{label}</Button>
      <FeedbackDialog open={open} email={email} username={username} onClose={() => setOpen(false)} />
    </>
  );
}
