import type { ButtonHTMLAttributes, MouseEvent } from 'react';
import { cx } from './cx';
import { Spinner } from './Spinner';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'text' | 'danger';
export type ButtonSize = 'md' | 'lg';

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 加载中：按钮进入 disabled 且不触发 onClick，视觉上保留原文案。 */
  loading?: boolean;
};

/** danger 只在确认弹层里出现，页面上的破坏性入口先用 secondary。 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  className,
  children,
  onClick,
  type = 'button',
  ...rest
}: ButtonProps) {
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (loading || disabled) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  }

  return (
    <button
      {...rest}
      type={type}
      className={cx(styles.button, styles[variant], styles[size], loading && styles.loading, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      onClick={handleClick}
    >
      {loading ? <Spinner /> : null}
      <span className={styles.label}>{children}</span>
    </button>
  );
}
