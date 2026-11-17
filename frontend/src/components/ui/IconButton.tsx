import type { ButtonHTMLAttributes } from 'react';
import { cx } from './cx';
import styles from './IconButton.module.css';

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** 必填：图标按钮没有可见文字，必须由 aria-label 提供名称。 */
  label: string;
};

export function IconButton({ label, className, children, type = 'button', ...rest }: IconButtonProps) {
  return (
    <button {...rest} type={type} aria-label={label} className={cx(styles.iconButton, className)}>
      {children}
    </button>
  );
}
