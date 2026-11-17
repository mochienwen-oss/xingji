import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import type { Day, Trip } from '../../types/trip';
import { diffTripDays, diffTripFields, mergeTripDays, totalStops } from './workspace';
import styles from './TripWorkspace.module.css';

function editedNote(trip: Trip): string | null {
  if (!trip.last_edited_by) return null;
  if (!trip.last_edited_at) return `${trip.last_edited_by} 最近保存`;
  const moment = new Date(trip.last_edited_at);
  if (Number.isNaN(moment.getTime())) return `${trip.last_edited_by} 最近保存`;
  const at = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(moment);
  return `${trip.last_edited_by} 最近保存 · ${at}`;
}

type Props = {
  open: boolean;
  busy: boolean;
  local: Trip | null;
  latest: Trip | null;
  onClose: () => void;
  onLoadLatest: () => void;
  onKeepMine: () => void;
  onDiscard: () => void;
  onMerge: (days: Day[]) => void;
};

/** 保存冲突：逐字段合并，或整体取舍，不替用户决定覆盖还是丢弃。 */
export function ConflictDialog({ open, busy, local, latest, onClose, onLoadLatest, onKeepMine, onDiscard, onMerge }: Props) {
  const fieldDiffs = useMemo(
    () => (local && latest ? diffTripFields(local.days, latest.days) : []),
    [local, latest],
  );
  const mergeable = useMemo(() => fieldDiffs.filter(diff => diff.merge !== null), [fieldDiffs]);
  const mergeableKey = mergeable.map(diff => diff.id).join('|');
  const [selected, setSelected] = useState<string[]>([]);
  const bodyRef = useRef<HTMLDivElement>(null);

  // 每次打开都默认采用全部线上修改；不可合并的整天替换仍可取消勾选。
  useEffect(() => {
    if (open) setSelected(mergeable.map(diff => diff.id));
    // mergeableKey 已覆盖字段集合的变化，避免因数组重建反复重置勾选。
  }, [open, mergeableKey]);

  const toggle = (id: string) => {
    setSelected(current => (current.includes(id) ? current.filter(item => item !== id) : [...current, id]));
  };

  const mergedDays = local && latest ? mergeTripDays(local.days, latest.days, selected) : [];
  const fallback = local && latest ? diffTripDays(local.days, latest.days) : [];
  const canMerge = mergeable.length > 0 && selected.length > 0 && Boolean(local && latest);

  return (
    <Dialog
      open={open}
      onClose={busy ? () => {} : onClose}
      title="这段行程在别处被修改过"
      initialFocusRef={bodyRef}
      busy={busy}
      footer={
        <>
          <Button variant="text" onClick={onDiscard} disabled={busy}>
            放弃修改
          </Button>
          <Button variant="secondary" onClick={onLoadLatest} disabled={busy}>
            载入最新
          </Button>
          <Button variant="secondary" onClick={onKeepMine} disabled={busy}>
            保留我的
          </Button>
          <Button onClick={() => onMerge(mergedDays)} loading={busy} disabled={!canMerge}>
            合并并保存
          </Button>
        </>
      }
    >
      <div ref={bodyRef} className={styles.conflictBody} tabIndex={-1}>
        <p>你的保存没有覆盖对方的新版本。可以勾选要采用的线上修改，其余保留你的版本。</p>
        {latest ? (
          <div className={styles.conflictVersions}>
            {local ? (
              <div className={styles.conflictSummary}>
                <span className={styles.conflictLabel}>你的未保存版本</span>
                <strong>{local.title || '未命名行程'}</strong>
                <span>{local.days.length} 天 · {totalStops(local.days)} 个地点</span>
              </div>
            ) : null}
            <div className={styles.conflictSummary}>
              <span className={styles.conflictLabel}>服务器最新</span>
              <strong>{latest.title || '未命名行程'}</strong>
              <span>{latest.days.length} 天 · {totalStops(latest.days)} 个地点</span>
              {editedNote(latest) ? <span className={styles.conflictEditor}>{editedNote(latest)}</span> : null}
            </div>
          </div>
        ) : (
          <p className={styles.conflictHint}>正在读取服务器上的最新版本…</p>
        )}

        {latest && fieldDiffs.length > 0 ? (
          <div className={styles.conflictDiff} data-conflict-diff>
            <span className={styles.conflictLabel}>逐项合并（勾选采用线上版本）</span>
            <ul className={styles.mergeList}>
              {fieldDiffs.map(diff => {
                const checked = selected.includes(diff.id);
                const disabled = busy || diff.merge === null;
                return (
                  <li key={diff.id}>
                    <label className={styles.mergeRow}>
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggle(diff.id)}
                        aria-label={diff.label}
                      />
                      <span className={styles.mergeCopy}>
                        <span className={styles.mergeLabel}>
                          {diff.label}
                          {diff.merge === 'day' ? <em>整天采用线上，本地这一天的改动会被替换</em> : null}
                        </span>
                        <span className={styles.mergeValues}>你的：{diff.local} · 线上：{diff.latest}</span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
            {mergeable.length === 0 ? (
              <p className={styles.conflictHint}>这次差异无法逐项合并，请选择载入最新或保留我的。</p>
            ) : null}
          </div>
        ) : null}

        {latest && fieldDiffs.length === 0 && fallback.length > 0 ? (
          <div className={styles.conflictDiff} data-conflict-diff>
            <span className={styles.conflictLabel}>差异概览（你的版本 → 线上）</span>
            <ul>
              {fallback.map(item => <li key={item.day + item.text}>{item.text}</li>)}
            </ul>
            <p className={styles.conflictHint}>这次差异无法逐项合并，请选择载入最新或保留我的。</p>
          </div>
        ) : null}

        <p className={styles.conflictHint}>
          「合并并保存」以你的版本为底，只替换勾选的字段；「载入最新」会丢弃本地修改；「保留我的」会用本地版本覆盖服务器。
        </p>
      </div>
    </Dialog>
  );
}
