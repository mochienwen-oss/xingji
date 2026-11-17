import type { ReactNode } from 'react';
import { Button } from './Button';
import { cx } from './cx';
import styles from './ErrorState.module.css';

export type ErrorStateProps = {
  title?: string;
  body?: ReactNode;
  /** 单一主行动：重试。 */
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
};

/** 错误态：衬线标题 + 一句可读说明 + 重试，不展示原始异常。 */
export function ErrorState({ title = '出了点问题', body, onRetry, retryLabel = '重试', className }: ErrorStateProps) {
  return (
    <section role="alert" className={cx(styles.error, className)}>
      <h2 className={styles.title}>{title}</h2>
      {body ? <p className={styles.body}>{body}</p> : null}
      {onRetry ? (
        <div className={styles.actions}>
          <Button onClick={onRetry}>{retryLabel}</Button>
        </div>
      ) : null}
    </section>
  );
}
