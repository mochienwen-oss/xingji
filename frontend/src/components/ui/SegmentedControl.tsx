import { useRef, type KeyboardEvent } from 'react';
import { cx } from './cx';
import styles from './SegmentedControl.module.css';

export type SegmentedOption<T extends string> = { value: T; label: string };

export type SegmentedControlProps<T extends string> = {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  /** tablist 的无障碍名称。 */
  label: string;
  className?: string;
};

/**
 * 分段控件：等宽分段、44px、选中项 2px 砖红底线。
 * roving tabindex + 左右箭头/Home/End，切换即选中（不额外确认）。
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: SegmentedControlProps<T>) {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);

  function handleKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = options.length - 1;
    let next = -1;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = index === last ? 0 : index + 1;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = index === 0 ? last : index - 1;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = last;
    if (next < 0) return;
    event.preventDefault();
    onChange(options[next].value);
    buttons.current[next]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} className={cx(styles.segmented, className)}>
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={node => {
              buttons.current[index] = node;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className={cx(styles.segment, selected && styles.selected)}
            onClick={() => onChange(option.value)}
            onKeyDown={event => handleKey(event, index)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
