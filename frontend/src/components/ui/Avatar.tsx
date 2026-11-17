import { coverInitials } from '../../lib/cover';
import { cx } from './cx';
import styles from './Avatar.module.css';

export type AvatarProps = {
  name: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
};

/** 首字头像：没有头像图片时用姓名首字 + 沙色底，形状始终是圆的。 */
export function Avatar({ name, size = 'md', className }: AvatarProps) {
  return (
    <span role="img" aria-label={name} className={cx(styles.avatar, styles[size], className)}>
      <span aria-hidden="true">{coverInitials(name)}</span>
    </span>
  );
}
