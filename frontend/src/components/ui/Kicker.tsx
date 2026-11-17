import type { HTMLAttributes } from 'react';
import { cx } from './cx';
import styles from './Kicker.module.css';

export type KickerProps = HTMLAttributes<HTMLSpanElement>;

/** 编辑式 kicker：11px、0.14em 字距、全大写。 */
export function Kicker({ className, children, ...rest }: KickerProps) {
  return (
    <span {...rest} className={cx(styles.kicker, className)}>
      {children}
    </span>
  );
}
