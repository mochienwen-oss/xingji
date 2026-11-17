import type { ButtonHTMLAttributes } from 'react';
import { cx } from './cx';
import styles from './Chip.module.css';

export type ChipProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  selected?: boolean;
};

/** 标签 chip：36px 视觉高度，热区补到 44px；选中态用 ink 底。 */
export function Chip({ selected = false, className, type = 'button', ...rest }: ChipProps) {
  return (
    <button
      {...rest}
      type={type}
      aria-pressed={selected}
      className={cx(styles.chip, selected && styles.selected, className)}
    />
  );
}
