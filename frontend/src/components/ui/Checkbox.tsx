import { useId, type InputHTMLAttributes, type ReactNode } from 'react';
import { CheckIcon } from '../icons';
import { cx } from './cx';
import styles from './Checkbox.module.css';

export type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  label: ReactNode;
  hint?: string;
  /** 外部布局 className 走整行容器；className 落在原生 input 上。 */
  containerClassName?: string;
};

/** 复选框：整行 44px 可点，原生 input 保留焦点与语义，视觉方框由 span 承担。 */
export function Checkbox({ label, hint, className, containerClassName, id, ...rest }: CheckboxProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = inputId + '-hint';

  return (
    <label className={cx(styles.row, containerClassName)} htmlFor={inputId}>
      <input
        {...rest}
        id={inputId}
        type="checkbox"
        className={cx(styles.input, className)}
        aria-describedby={hint ? hintId : undefined}
      />
      <span className={styles.box} aria-hidden="true">
        <CheckIcon size={14} />
      </span>
      <span className={styles.text}>
        <span className={styles.label}>{label}</span>
        {hint ? (
          <span id={hintId} className={styles.hint}>
            {hint}
          </span>
        ) : null}
      </span>
    </label>
  );
}
