import { useEffect, useId, useState, type FormEvent } from 'react';
import { message } from '../lib/api';
import {
  REPORT_REASONS,
  sendReport,
  type ReportReason,
  type ReportTarget,
} from '../lib/reports';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';
import styles from './ReportDialog.module.css';

type Lang = 'zh' | 'en';

const COPY = {
  zh: {
    title: '举报这份行程',
    intro: '如果内容违法、侵权、虚假或属于广告，请告诉我们。提交后由运营人工核查。',
    reasonLabel: '问题类型',
    detailLabel: '补充说明（可选）',
    detailPlaceholder: '请描述具体问题，例如哪个地点或哪句话有问题。',
    hint: '不要填写密码、身份证等敏感信息。',
    counter: (n: number, max: number) => n + '/' + max,
    submit: '提交举报',
    submitting: '正在提交…',
    cancel: '取消',
    close: '关闭',
    success: (duplicate: boolean) => duplicate
      ? '你已经举报过这份行程，运营会在 24 小时内核查。'
      : '已收到举报，我们会在 24 小时内核查。',
    error: '举报没有提交成功，请稍后再试。',
    reasons: ['虚假信息', '违法违规', '侵犯隐私', '垃圾广告', '其他'],
  },
  en: {
    title: 'Report this trip',
    intro: 'If this content is illegal, infringing, false, or spam, tell us. A human will review the report.',
    reasonLabel: 'Issue type',
    detailLabel: 'Additional details (optional)',
    detailPlaceholder: 'Describe the problem, such as a specific place or sentence.',
    hint: "Please don't include passwords or ID numbers.",
    counter: (n: number, max: number) => n + '/' + max,
    submit: 'Submit report',
    submitting: 'Submitting…',
    cancel: 'Cancel',
    close: 'Close',
    success: (duplicate: boolean) => duplicate
      ? 'You already reported this trip. We will review it within 24 hours.'
      : 'Report received. We will review it within 24 hours.',
    error: 'The report could not be sent. Please try again.',
    reasons: ['False information', 'Illegal content', 'Privacy violation', 'Spam', 'Other'],
  },
} as const;

const DETAIL_LIMIT = 1000;

export type ReportDialogProps = {
  open: boolean;
  target: ReportTarget | null;
  onClose: () => void;
  lang?: Lang;
};

/** 举报弹层：广场与分享页共用；成功后只显示结果，不再重复提交。 */
export function ReportDialog({ open, target, onClose, lang = 'zh' }: ReportDialogProps) {
  const copy = COPY[lang];
  const [reason, setReason] = useState<ReportReason>(REPORT_REASONS[0]);
  const [detail, setDetail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<{ duplicate: boolean } | null>(null);
  const formId = useId();
  const reasonId = useId();
  const detailId = useId();
  // 父组件每次渲染都会新建 target 对象；只在「目标值」变化时重置，避免输入被清空。
  const targetKey = target
    ? (target.kind === 'trip' ? 'trip:' + target.id : 'share:' + target.token)
    : '';

  useEffect(() => {
    if (!open) return;
    setReason(REPORT_REASONS[0]);
    setDetail('');
    setBusy(false);
    setError('');
    setDone(null);
  }, [open, targetKey]);

  function close() {
    if (busy) return;
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!target || busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await sendReport(target, reason, detail);
      setDone({ duplicate: result.duplicate });
    } catch (reasonError) {
      setError(message(reasonError) || copy.error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={copy.title}
      busy={busy}
      footer={done ? (
        <Button onClick={close}>{copy.close}</Button>
      ) : (
        <>
          <Button variant="text" onClick={close} disabled={busy}>{copy.cancel}</Button>
          <Button type="submit" form={formId} loading={busy}>{busy ? copy.submitting : copy.submit}</Button>
        </>
      )}
    >
      {done ? (
        <p className={styles.status} role="status">{copy.success(done.duplicate)}</p>
      ) : (
        <form id={formId} className={styles.form} onSubmit={handleSubmit} noValidate>
          <p className={styles.intro}>{copy.intro}</p>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={reasonId}>{copy.reasonLabel}</label>
            <select
              id={reasonId}
              className={styles.select}
              value={reason}
              onChange={event => setReason(event.target.value as ReportReason)}
            >
              {REPORT_REASONS.map((value, index) => (
                <option key={value} value={value}>{copy.reasons[index]}</option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={detailId}>{copy.detailLabel}</label>
            <textarea
              id={detailId}
              className={styles.textarea}
              value={detail}
              maxLength={DETAIL_LIMIT}
              placeholder={copy.detailPlaceholder}
              onChange={event => setDetail(event.target.value)}
            />
            <div className={styles.meta}>
              <span className={styles.hint}>{copy.hint}</span>
              <span className={styles.counter}>{copy.counter(detail.length, DETAIL_LIMIT)}</span>
            </div>
          </div>
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
        </form>
      )}
    </Dialog>
  );
}
