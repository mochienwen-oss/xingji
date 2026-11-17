import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import type { TripSummary } from '../../types/trip';
import { MoreIcon } from '../icons';
import { TripCover } from '../trip/TripCover';
import { IconButton } from '../ui/IconButton';
import styles from './TripCard.module.css';
import { summaryMeta, tripName } from './tripMeta';

export type TripCardAction = 'rename' | 'delete';

export type TripCardProps = {
  trip: TripSummary;
  onOpen: (trip: TripSummary) => void;
  onAction: (trip: TripSummary, action: TripCardAction) => void;
};

const MENU: ReadonlyArray<{ action: TripCardAction; label: string }> = [
  { action: 'rename', label: '重命名' },
  { action: 'delete', label: '删除' },
];

/**
 * 我的行程卡片：封面 + 标题 + 城市/天数/日期，右上角 ⋯ 菜单。
 * 整张卡是一个覆盖式按钮，菜单浮在它上面（z-index），保证键盘和读屏都能用。
 */
export function TripCard({ trip, onOpen, onAction }: TripCardProps) {
  const titleId = useId();
  const name = tripName(trip);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const firstItemRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    firstItemRef.current?.focus();

    const onPointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node | null;
      if (target && menuRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setMenuOpen(false);
      triggerRef.current?.querySelector('button')?.focus();
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('touchstart', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('touchstart', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [menuOpen]);

  const choose = (action: TripCardAction) => {
    setMenuOpen(false);
    onAction(trip, action);
  };

  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    );
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === 'ArrowDown'
        ? (index + 1) % items.length
        : (index - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  return (
    <article className={styles.card}>
      <div className={styles.media}>
        <TripCover city={trip.city} />
      </div>
      <div className={styles.text}>
        <h2 className={styles.title} id={titleId}>
          {name}
        </h2>
        <p className={styles.meta}>{summaryMeta(trip)}</p>
      </div>
      <button
        type="button"
        className={styles.hit}
        aria-labelledby={titleId}
        onClick={() => onOpen(trip)}
      />
      <div className={styles.menu} ref={menuRef}>
        <span ref={triggerRef} className={styles.triggerWrap}>
          <IconButton
            label={'更多操作：' + name}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className={styles.trigger}
            onClick={() => setMenuOpen(open => !open)}
          >
            <MoreIcon size={20} />
          </IconButton>
        </span>
        {menuOpen ? (
          <div
            className={styles.menuList}
            role="menu"
            aria-label={name + ' 的更多操作'}
            onKeyDown={onMenuKeyDown}
          >
            {MENU.map((item, index) => (
              <button
                key={item.action}
                ref={index === 0 ? firstItemRef : undefined}
                type="button"
                role="menuitem"
                className={
                  item.action === 'delete'
                    ? styles.menuItem + ' ' + styles.menuDanger
                    : styles.menuItem
                }
                onClick={() => choose(item.action)}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}
