import type { MouseEvent } from 'react';
import { CompassIcon, RouteIcon, UserIcon, UsersIcon } from '../icons';
import styles from './BottomNav.module.css';

export type NavTab = 'explore' | 'trips' | 'collab' | 'profile';

export const NAV_TABS: { id: NavTab; label: string; href: string; Icon: typeof CompassIcon }[] = [
  { id: 'explore', label: '探索', href: '#/explore', Icon: CompassIcon },
  { id: 'trips', label: '行程', href: '#/trips', Icon: RouteIcon },
  { id: 'collab', label: '协同', href: '#/collab', Icon: UsersIcon },
  { id: 'profile', label: '我的', href: '#/profile', Icon: UserIcon },
];

type Props = {
  active: NavTab;
  onNavigate: (path: string, options?: { replace?: boolean }) => void;
};

/** 移动端底部导航：56px + 安全区，当前项用 2px 砖红指示条标记。 */
export function BottomNav({ active, onNavigate }: Props) {
  function go(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(href.replace(/^#/, ''), { replace: true });
  }

  return (
    <nav className={styles.nav} aria-label="主导航">
      {NAV_TABS.map(({ id, label, href, Icon }) => {
        const current = id === active;
        return (
          <a
            key={id}
            className={styles.tab}
            href={href}
            aria-current={current ? 'page' : undefined}
            onClick={event => go(event, href)}
          >
            <span className={styles.indicator} aria-hidden="true" />
            <Icon size={22} />
            <span className={styles.label}>{label}</span>
          </a>
        );
      })}
    </nav>
  );
}
