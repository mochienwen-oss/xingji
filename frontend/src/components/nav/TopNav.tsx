import type { MouseEvent } from 'react';
import type { SessionUser } from '../../app/providers/SessionProvider';
import { NAV_TABS, type NavTab } from './BottomNav';
import styles from './TopNav.module.css';

type Props = {
  active: NavTab;
  user: SessionUser | null;
  onNavigate: (path: string, options?: { replace?: boolean }) => void;
  onLogin: () => void;
};

/** 桌面端顶部导航：64px，左侧 wordmark，中间三 tab，右侧账户入口。 */
export function TopNav({ active, user, onNavigate, onLogin }: Props) {
  function go(event: MouseEvent<HTMLAnchorElement>, path: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(path);
  }

  return (
    <header className={styles.header}>
      <a className={styles.brand} href="#/explore" onClick={event => go(event, '/explore')}>
        行迹<span aria-hidden="true">·</span>
      </a>
      <nav className={styles.tabs} aria-label="主导航">
        {NAV_TABS.map(tab => (
          <a
            key={tab.id}
            className={styles.tab}
            href={tab.href}
            aria-current={tab.id === active ? 'page' : undefined}
            onClick={event => go(event, tab.href.replace(/^#/, ''))}
          >
            {tab.label}
          </a>
        ))}
      </nav>
      <div className={styles.actions}>
        {user ? (
          <button type="button" className={styles.avatar} onClick={() => onNavigate('/profile')} aria-label="打开我的">
            {user.username.slice(0, 1).toUpperCase()}
          </button>
        ) : (
          <button type="button" className={styles.login} onClick={onLogin}>
            登录
          </button>
        )}
      </div>
    </header>
  );
}
