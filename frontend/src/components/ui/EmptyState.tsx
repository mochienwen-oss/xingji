import type { ReactNode } from 'react';
import { Kicker } from './Kicker';
import { cx } from './cx';
import styles from './EmptyState.module.css';

export type EmptyStateProps = {
  kicker?: string;
  title: string;
  body?: ReactNode;
  /** 唯一主行动。 */
  action?: ReactNode;
  /** 可选次行动（文本按钮或链接）。 */
  secondaryAction?: ReactNode;
  className?: string;
};

/** 空态：kicker + 26px 衬线主张 + 一句说明 + 1 个主行动。 */
export function EmptyState({ kicker, title, body, action, secondaryAction, className }: EmptyStateProps) {
  return (
    <section className={cx(styles.empty, className)}>
      {kicker ? <Kicker className={styles.kicker}>{kicker}</Kicker> : null}
      <h2 className={styles.title}>{title}</h2>
      {body ? <p className={styles.body}>{body}</p> : null}
      {action || secondaryAction ? (
        <div className={styles.actions}>
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </section>
  );
}
