import { useId, type InputHTMLAttributes, type ReactNode, type Ref } from 'react';
import { cx } from './cx';
import styles from './TextField.module.css';

export type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string;
  /** 右侧附加操作（如密码显示切换），由外层组件传入。 */
  trailing?: ReactNode;
  /** 外部布局 className 走容器；className 作用在 input 本身。 */
  containerClassName?: string;
  /** 需要从外部聚焦/选中输入框时传入。 */
  inputRef?: Ref<HTMLInputElement>;
};

/**
 * 输入框：48px、纸底、1px 发丝线、focus 2px 靛蓝。
 * label / hint / error 通过 aria-describedby 关联，读屏能一次读全。
 */
export function TextField({
  label,
  hint,
  error,
  trailing,
  className,
  containerClassName,
  inputRef,
  id,
  ...rest
}: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = inputId + '-hint';
  const errorId = inputId + '-error';
  const describedBy = [hint ? hintId : '', error ? errorId : ''].filter(Boolean).join(' ') || undefined;

  return (
    <div className={cx(styles.field, containerClassName)}>
      <label className={styles.label} htmlFor={inputId}>
        {label}
      </label>
      <div className={cx(styles.control, trailing ? styles.withTrailing : undefined)}>
        <input
          {...rest}
          ref={inputRef}
          id={inputId}
          className={cx(styles.input, error && styles.invalid, className)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
        />
        {trailing ? <span className={styles.trailing}>{trailing}</span> : null}
      </div>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
