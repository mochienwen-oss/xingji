import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Collaborator } from '../../types/trip';
import { BackIcon, MoreIcon } from '../icons';
import { IconButton } from '../ui/IconButton';
import { cx } from '../ui/cx';
import { initialOf } from './workspace';
import styles from './TripWorkspace.module.css';

export type TripMenuAction = 'budget' | 'nearby' | 'guide' | 'optimize' | 'delete';
export type WorkspaceSyncState = 'synced' | 'saving' | 'offline';

type Props = {
  title: string;
  collaborators: Collaborator[];
  syncState: WorkspaceSyncState;
  /** 当前天是否有两个以上站点；不满足时整个优化入口不出现。 */
  optimizeVisible: boolean;
  /** 有未保存修改或正在请求时，优化入口可见但不可点。 */
  optimizeAvailable: boolean;
  optimizeBusy: boolean;
  shareSlot?: ReactNode;
  /** 仅创建者能重命名和删除；协作者只看到只读标题与协作菜单。 */
  canManage?: boolean;
  onBack: () => void;
  onRename: () => void;
  onMembers: () => void;
  onMenuAction: (action: TripMenuAction) => void;
};

const SYNC_LABELS: Record<WorkspaceSyncState, string> = {
  synced: '已同步',
  saving: '同步中',
  offline: '离线，修改会暂存在本机',
};

function MenuItem({
  action,
  disabled,
  danger,
  onSelect,
  children,
}: {
  action: TripMenuAction;
  disabled?: boolean;
  danger?: boolean;
  onSelect: (action: TripMenuAction) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className={cx(styles.menuItem, danger && styles.menuDanger)}
      disabled={disabled}
      onClick={() => onSelect(action)}
    >
      {children}
    </button>
  );
}

/** 56px 行程头：返回、可重命名标题、分享、更多、协作者与同步点。 */
export function TripHeader({
  title,
  collaborators,
  syncState,
  optimizeVisible,
  optimizeAvailable,
  optimizeBusy,
  shareSlot,
  canManage = true,
  onBack,
  onRename,
  onMembers,
  onMenuAction,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  function select(action: TripMenuAction) {
    setMenuOpen(false);
    onMenuAction(action);
  }

  const visible = collaborators.slice(0, 3);
  const rest = collaborators.length - visible.length;
  const syncLabel = SYNC_LABELS[syncState];

  return (
    <header className={styles.header}>
      <h1 className={styles.srTitle}>{title}</h1>
      <div className={styles.headerInner}>
        <IconButton label="返回" className={styles.headerButton} onClick={onBack}>
          <BackIcon />
        </IconButton>

        {canManage ? (
          <button
            type="button"
            className={styles.titleButton}
            aria-label={`重命名行程：${title}`}
            title="点击重命名"
            onClick={onRename}
          >
            {title}
          </button>
        ) : (
          <span className={styles.titleStatic} title={title}>{title}</span>
        )}

        <div className={styles.headerActions}>
          {shareSlot ? <div className={styles.shareSlot}>{shareSlot}</div> : null}

          <div className={styles.menuWrap} ref={menuRef}>
            <IconButton
              label="更多操作"
              className={styles.headerButton}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(value => !value)}
            >
              <MoreIcon />
            </IconButton>
            {menuOpen ? (
              <div className={styles.menu} role="menu" aria-label="行程操作">
                <MenuItem action="budget" onSelect={select}>预算</MenuItem>
                <MenuItem action="nearby" onSelect={select}>附近</MenuItem>
                <MenuItem action="guide" onSelect={select}>导入攻略</MenuItem>
                {optimizeVisible ? (
                  <MenuItem action="optimize" disabled={!optimizeAvailable || optimizeBusy} onSelect={select}>
                    {optimizeBusy ? '优化中…' : '优化今天路线'}
                  </MenuItem>
                ) : null}
                {canManage ? (
                  <>
                    <div className={styles.menuRule} aria-hidden="true" />
                    <MenuItem action="delete" danger onSelect={select}>删除行程</MenuItem>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>

          {visible.length > 0 ? (
            <button
              type="button"
              className={styles.membersButton}
              aria-label={`查看协作者，共 ${collaborators.length} 人`}
              onClick={onMembers}
            >
              <span className={styles.avatarStack} aria-hidden="true">
                {visible.map(member => (
                  <span key={member.user_id} className={styles.avatar}>
                    {initialOf(member.username)}
                  </span>
                ))}
              </span>
              {rest > 0 ? <span className={styles.avatarMore} aria-hidden="true">+{rest}</span> : null}
            </button>
          ) : null}

          <span
            className={styles.syncDot}
            data-state={syncState}
            role="img"
            aria-label={syncLabel}
            title={syncLabel}
          />
        </div>
      </div>
    </header>
  );
}
