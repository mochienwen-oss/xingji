import type { ReactNode } from 'react';
import { cx } from './cx';
import styles from './AiNotice.module.css';

export type AiNoticeProps = {
  children?: ReactNode;
  className?: string;
};

/**
 * 《人工智能生成合成内容标识办法》要求的显式标识。
 * 所有由模型生成、再交给用户确认的行程内容都应带这行说明。
 */
export function AiNotice({ children, className }: AiNoticeProps) {
  return (
    <p className={cx(styles.notice, className)} role="note">
      <span className={styles.badge} aria-hidden="true">AI</span>
      <span className={styles.text}>{children ?? '行程由 AI 生成，地点与时间请在出发前核实。'}</span>
    </p>
  );
}
