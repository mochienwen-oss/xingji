import { useId } from 'react';
import type { SharedTripSummary } from '../../types/trip';
import { ArrowRightIcon } from '../icons';
import styles from './SharedTripRow.module.css';
import { tripName } from './tripMeta';

export type SharedTripRowProps = {
  share: SharedTripSummary;
  onOpen: (share: SharedTripSummary) => void;
  /** 协作者席位才给「退出协作」；不传就只读展示，保持旧用法兼容。 */
  onLeave?: (share: SharedTripSummary) => void;
  leaving?: boolean;
};

/**
 * 列表副标题：城市 · @创建者 创建 · 共 N 人协作。
 * 后端字段可能缺失（旧行程或未登录视角），缺什么就少显示什么，不编造。
 */
export function sharedMeta(share: SharedTripSummary): string {
  const parts: string[] = [share.city];
  if (share.owner) parts.push('@' + share.owner + ' 创建');
  if (typeof share.member_count === 'number' && share.member_count > 0) {
    parts.push('共 ' + share.member_count + ' 人协作');
  }
  return parts.join(' · ');
}

/**
 * 协作列表的一行：显示创建者、成员数、在线人数，并给协作者一个「退出协作」。
 * onLeave 不传时退化成纯展示行（只读视角复用同一份 UI）。
 */
export function SharedTripRow({ share, onOpen, onLeave, leaving = false }: SharedTripRowProps) {
  const titleId = useId();
  const name = tripName(share);
  const editable = share.role === 'edit' || share.role === 'owner';
  const online = typeof share.online === 'number' ? share.online : 0;

  return (
    <article className={styles.row}>
      <div className={styles.text}>
        <h2 className={styles.title} id={titleId}>
          {name}
        </h2>
        <p className={styles.meta}>{sharedMeta(share)}</p>
        {online > 0 ? (
          <p className={styles.presence}>
            <span className={styles.dot} aria-hidden="true" />
            {online} 人在线
          </p>
        ) : null}
      </div>
      <span className={styles.badge}>{editable ? '可编辑' : '只读'}</span>
      {onLeave ? (
        <button
          type="button"
          className={styles.leave}
          disabled={leaving}
          onClick={() => onLeave(share)}
        >
          {leaving ? '正在退出…' : '退出协作'}
        </button>
      ) : null}
      <ArrowRightIcon className={styles.arrow} size={20} />
      <button
        type="button"
        className={styles.hit}
        aria-labelledby={titleId}
        onClick={() => onOpen(share)}
      />
    </article>
  );
}
