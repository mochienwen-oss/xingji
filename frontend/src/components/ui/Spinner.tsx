import { cx } from './cx';
import styles from './Spinner.module.css';

export type SpinnerProps = {
  /** 传入后作为 status 播报；不传则纯装饰，由按钮的 aria-busy 表达状态。 */
  label?: string;
  size?: number;
  className?: string;
};

export function Spinner({ label, size = 16, className }: SpinnerProps) {
  const decorative = !label;
  return (
    <span
      className={cx(styles.spinner, className)}
      role={decorative ? undefined : 'status'}
      aria-hidden={decorative ? true : undefined}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="12" r="9" opacity=".25" />
        <path d="M21 12a9 9 0 0 0-9-9" />
      </svg>
      {label ? <span className={styles.label}>{label}</span> : null}
    </span>
  );
}
