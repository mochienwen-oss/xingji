import { useRef, type KeyboardEvent, type ReactNode } from 'react';

export type SegmentedTabItem = { id: string; label: ReactNode };

type Props = {
  tabs: SegmentedTabItem[];
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  /** 用于成对生成 tab / tabpanel 的 id。 */
  idPrefix: string;
  className?: string;
};

/** 分段标签：roving tabIndex + 左右循环 + Home/End，外观沿用原有的下划线 / 胶囊样式。 */
export function SegmentedTabs({ tabs, value, onChange, ariaLabel, idPrefix, className = 'day-tabs' }: Props) {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);

  function handleKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = tabs.length - 1;
    let next = -1;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = index === last ? 0 : index + 1;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = index === 0 ? last : index - 1;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = last;
    if (next < 0) return;
    event.preventDefault();
    onChange(tabs[next].id);
    buttons.current[next]?.focus();
  }

  return (
    <div className={className} role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab, index) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={node => { buttons.current[index] = node; }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${tab.id}`}
            aria-controls={`${idPrefix}-panel-${tab.id}`}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            className={active ? 'active' : ''}
            onClick={() => onChange(tab.id)}
            onKeyDown={event => handleKey(event, index)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

/** tabpanel 属性：与 SegmentedTabs 的 aria-controls 对齐，可聚焦以便键盘读屏用户进入面板。 */
export function tabPanel(idPrefix: string, id: string) {
  return {
    role: 'tabpanel' as const,
    id: `${idPrefix}-panel-${id}`,
    'aria-labelledby': `${idPrefix}-tab-${id}`,
    tabIndex: 0,
  };
}
