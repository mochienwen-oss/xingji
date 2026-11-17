import { useEffect, useRef, type KeyboardEvent } from 'react';
import type { Day } from '../../types/trip';
import { cx } from '../ui/cx';
import { dayTabLabel } from './workspace';
import styles from './TripWorkspace.module.css';

type Props = {
  days: Day[];
  selected: number;
  startDate?: string | null;
  backlogCount: number;
  onSelect: (index: number) => void;
  onBacklog: () => void;
};

/** 44px 日期 tabs：选中项 2px 砖红底线，待规划入口只在有内容时出现。 */
export function DayTabs({ days, selected, startDate, backlogCount, onSelect, onBacklog }: Props) {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    buttons.current[selected]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [selected]);

  function handleKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = days.length - 1;
    let next = -1;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = index === last ? 0 : index + 1;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = index === 0 ? last : index - 1;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = last;
    if (next < 0) return;
    event.preventDefault();
    onSelect(next);
    buttons.current[next]?.focus();
  }

  return (
    <div className={styles.tabsRow}>
      <div className={styles.dayTabs} role="tablist" aria-label="行程日期">
        {days.map((day, index) => {
          const active = index === selected;
          return (
            <button
              key={index}
              ref={node => {
                buttons.current[index] = node;
              }}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls="day-panel"
              tabIndex={active ? 0 : -1}
              className={cx(styles.dayTab, active && styles.dayTabActive)}
              onClick={() => onSelect(index)}
              onKeyDown={event => handleKey(event, index)}
            >
              {dayTabLabel(index, startDate)}
            </button>
          );
        })}
      </div>
      {backlogCount > 0 ? (
        <button
          type="button"
          className={styles.backlogTab}
          aria-haspopup="dialog"
          onClick={onBacklog}
        >
          待规划 <span className={styles.backlogBadge}>{backlogCount}</span>
        </button>
      ) : null}
    </div>
  );
}
