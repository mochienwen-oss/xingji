import { useState } from 'react';
import { EyeIcon, EyeOffIcon } from '../icons';
import { TextField, type TextFieldProps } from './TextField';
import styles from './PasswordField.module.css';

export type PasswordFieldProps = Omit<TextFieldProps, 'type' | 'trailing'>;

/** 密码框：在 TextField 上加 44x44 的显示/隐藏切换，状态用 aria-pressed 表达。 */
export function PasswordField(props: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <TextField
      {...props}
      type={visible ? 'text' : 'password'}
      trailing={
        <button
          type="button"
          className={styles.toggle}
          aria-pressed={visible}
          aria-label={visible ? '隐藏密码' : '显示密码'}
          onClick={() => setVisible(value => !value)}
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      }
    />
  );
}
