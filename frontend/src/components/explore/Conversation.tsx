import type { ChatMessage } from '../../types/trip';
import styles from './Conversation.module.css';

export type ConversationProps = {
  messages: ChatMessage[];
  streaming: string;
  busy: boolean;
  status: string;
  /** 生成中可中止：探索页生成最长要几十秒，没有出口时用户只能刷新页面。 */
  onCancel?: () => void;
};

export function Conversation({ messages, streaming, busy, status, onCancel }: ConversationProps) {
  if (!messages.length && !streaming && !busy) {
    return (
      <p className={styles.empty}>
        还没有聊过。说说你想怎么玩，比如「杭州 3 天，想走路多、少排队」。
      </p>
    );
  }

  return (
    <div className={styles.messages} role="log" aria-label="规划对话">
      {messages.map((message, index) => (
        <div
          key={`${message.role}-${index}`}
          className={message.role === 'user' ? `${styles.message} ${styles.user}` : `${styles.message} ${styles.assistant}`}
        >
          <span className={styles.label}>{message.role === 'user' ? '我' : '行迹 AI'}</span>
          <p className={styles.bubble}>{message.content}</p>
        </div>
      ))}
      {streaming ? (
        <div className={`${styles.message} ${styles.assistant}`}>
          <span className={styles.label}>行迹 AI</span>
          <p className={styles.bubble}>{streaming}</p>
        </div>
      ) : null}
      {busy && streaming && status ? (
        <p className={styles.statusLine} role="status">{status}</p>
      ) : null}
      {busy && !streaming ? (
        <div className={`${styles.message} ${styles.assistant}`}>
          <span className={styles.label}>行迹 AI</span>
          <p className={`${styles.bubble} ${styles.typing}`} role="status">{status || '正在理解需求…'}</p>
        </div>
      ) : null}
      {busy && onCancel ? (
        <button type="button" className={styles.cancel} onClick={onCancel}>
          停止生成
        </button>
      ) : null}
    </div>
  );
}
