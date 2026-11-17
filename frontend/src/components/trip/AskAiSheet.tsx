import { useState, type Dispatch, type SetStateAction } from 'react';
import type { ChatMessage, Day, Stop, Trip } from '../../types/trip';
import { TravelChat } from '../TravelChat';
import { Sheet } from '../ui/Sheet';
import styles from './TripWorkspace.module.css';

type Props = {
  open: boolean;
  trip: Trip | null;
  dirty: boolean;
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  onClose: () => void;
  onSuggestion: (days: Day[], backlog: Stop[]) => void;
  /** AI 对话落库后的版本回执：对齐本地 CAS 版本，避免应用建议后保存 409。 */
  ackVersion?: (version: number) => void;
  onRefreshTrip: () => Promise<boolean>;
  onNotify: (text: string) => void;
  undoAvailable?: boolean;
  onUndo?: () => void;
};

/** 全屏问 AI：沿用 TravelChat 的会话与建议保存语义，不改它的请求/版本逻辑。 */
export function AskAiSheet({
  open,
  trip,
  dirty,
  messages,
  setMessages,
  onClose,
  onSuggestion,
  ackVersion,
  onRefreshTrip,
  onNotify,
  undoAvailable,
  onUndo,
}: Props) {
  const [detent, setDetent] = useState<'peek' | 'half' | 'full'>('full');

  return (
    <Sheet open={open} detent={detent} onDetentChange={setDetent} onClose={onClose} labelledBy="ask-ai-title">
      <div className={styles.askAi}>
        <div className={styles.askAiHead}>
          <h2 id="ask-ai-title" className={styles.sheetTitle}>问 AI</h2>
          <p className={styles.sheetHint}>让它调整路线、补一个地点，或解释为什么这样排。</p>
        </div>
        {undoAvailable && onUndo ? (
          <div className={styles.askAiUndo} role="group" aria-label="AI 调整">
            <span>已应用 AI 调整</span>
            <button type="button" className={styles.askAiUndoButton} onClick={onUndo}>撤销</button>
          </div>
        ) : null}
        {dirty ? (
          <p className={styles.askAiDirty} role="status">
            有未保存的修改。先保存或放弃，才能把 AI 建议应用到行程。
          </p>
        ) : null}
        {trip ? (
          <div className={styles.askAiBody}>
            <TravelChat
              form={trip.request}
              messages={messages}
              setMessages={setMessages}
              trip={trip}
              dirty={dirty}
              onSuggestion={onSuggestion}
              onVersion={ackVersion}
              onRefreshTrip={onRefreshTrip}
              onNotify={onNotify}
            />
          </div>
        ) : (
          <p className={styles.sheetHint}>行程加载后就可以开始对话。</p>
        )}
      </div>
    </Sheet>
  );
}
