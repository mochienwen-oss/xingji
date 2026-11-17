import { ArrowRightIcon } from '../icons';
import styles from './Composer.module.css';

export type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onGenerate: () => void;
  canGenerate: boolean;
  generating: boolean;
  busy: boolean;
  city: string;
  hasPreview?: boolean;
  onOpenPreview?: () => void;
};

export function Composer({
  value,
  onChange,
  onSubmit,
  onGenerate,
  canGenerate,
  generating,
  busy,
  city,
  hasPreview = false,
  onOpenPreview,
}: ComposerProps) {
  const disabled = busy || generating;
  const sendDisabled = disabled || !value.trim();

  return (
    <div className={styles.dock}>
      {city ? (
        <div className={styles.meta}>
          <span className={styles.destination}>目的地 · {city}</span>
          {hasPreview && onOpenPreview ? (
            <button type="button" className={styles.planButton} onClick={onOpenPreview}>
              查看路线
            </button>
          ) : null}
          {canGenerate ? (
            <button
              type="button"
              className={styles.planButton}
              disabled={!canGenerate || disabled}
              onClick={onGenerate}
            >
              {generating ? '正在生成…' : '生成行程'}
            </button>
          ) : null}
        </div>
      ) : null}
      <div className={styles.row}>
        <textarea
          className={styles.input}
          rows={1}
          value={value}
          placeholder={hasPreview ? '继续说想怎么改，例如：第二天轻松一点' : '想去哪、怎么玩？例如：杭州 3 天'}
          aria-label="说说你想怎么玩"
          maxLength={2000}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || event.shiftKey) return;
            if (event.nativeEvent.isComposing) return;
            event.preventDefault();
            if (!sendDisabled) onSubmit();
          }}
        />
        <button
          type="button"
          className={styles.send}
          aria-label="发送"
          disabled={sendDisabled}
          onClick={onSubmit}
        >
          <ArrowRightIcon size={20} />
        </button>
      </div>
    </div>
  );
}