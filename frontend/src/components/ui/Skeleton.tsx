import type { HTMLAttributes } from 'react';
import { cx } from './cx';
import styles from './Skeleton.module.css';

export type SkeletonProps = HTMLAttributes<HTMLSpanElement>;

/** 骨架：纸-2 底 + 明暗呼吸；reduced-motion 时静态。 */
export function Skeleton({ className, children, ...rest }: SkeletonProps) {
  return (
    <span {...rest} aria-hidden="true" className={cx(styles.skeleton, className)}>
      {children}
    </span>
  );
}
