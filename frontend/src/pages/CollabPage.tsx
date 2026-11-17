import { useEffect, useState } from 'react';
import { useSession } from '../app/providers/SessionProvider';
import { useConfirm, useToast } from '../app/providers/ToastProvider';
import { useHashRoute } from '../app/routing/useHashRoute';
import { api, message } from '../lib/api';
import { openAuth } from '../lib/auth-events';
import { SharedTripRow } from '../components/trips/SharedTripRow';
import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Kicker } from '../components/ui/Kicker';
import { Skeleton } from '../components/ui/Skeleton';
import styles from './CollabPage.module.css';
import type { SharedTripSummary } from '../types/trip';

/** 在线人数来自实时房间，15 秒刷一次就够看出「有人同看」，不必开长连接。 */
const REFRESH_MS = 15_000;

function sortByOnline(a: SharedTripSummary, b: SharedTripSummary): number {
  return (b.online ?? 0) - (a.online ?? 0) || a.id - b.id;
}

/**
 * 协同：只列「别人共享给我、我是协作者」的行程。
 * 自己的行程留在「行程 → 我的」，两边数据隔开，避免混在一起。
 */
export function CollabPage() {
  const { user, loading } = useSession();
  const { navigate } = useHashRoute();
  const confirm = useConfirm();
  const { toast } = useToast();
  const [trips, setTrips] = useState<SharedTripSummary[] | null>(null);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [leavingId, setLeavingId] = useState<number | null>(null);
  const username = user?.username ?? '';

  useEffect(() => {
    if (!username) {
      setTrips(null);
      setError('');
      return;
    }
    let alive = true;
    let inFlight = false;

    async function load(silent: boolean) {
      if (inFlight) return;
      inFlight = true;
      try {
        const data = await api<{ trips: SharedTripSummary[] }>('/trips/shared');
        if (!alive) return;
        // 再挡一层 is_owner：后端已按协作者过滤，但旧数据曾把自己的公开行程也塞进来。
        setTrips((data.trips ?? []).filter(item => item.is_owner !== true).sort(sortByOnline));
        setError('');
      } catch (reason) {
        if (!alive) return;
        // 静默刷新失败保留旧列表，不闪错误；只有首屏失败才给重试入口。
        if (!silent) setError(message(reason));
      } finally {
        inFlight = false;
      }
    }

    void load(false);
    const timer = window.setInterval(() => {
      void load(true);
    }, REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [username, reloadKey]);

  async function handleLeave(share: SharedTripSummary) {
    const ok = await confirm({
      title: '退出这份协作行程？',
      body: '只会从你的协同列表移除，创建者和其他协作者不受影响；之后仍可用分享码重新加入。',
      confirmLabel: '退出协作',
      danger: true,
    });
    if (!ok) return;
    setLeavingId(share.id);
    try {
      await api(`/trips/${share.id}/members/me`, { method: 'DELETE' });
      setTrips(current => (current ?? []).filter(item => item.id !== share.id));
      setReloadKey(key => key + 1);
      toast('已退出协作。', 'success');
    } catch (reason) {
      toast(message(reason), 'error');
    } finally {
      setLeavingId(null);
    }
  }

  if (loading) {
    return (
      <main className={styles.page}>
        <div className={styles.shell} role="status" aria-live="polite">
          <Skeleton className={styles.skeletonKicker} />
          <Skeleton className={styles.skeletonTitle} />
          <Skeleton className={styles.skeletonRow} />
          <Skeleton className={styles.skeletonRow} />
          <span className={styles.srOnly}>正在加载协同行程…</span>
        </div>
      </main>
    );
  }

  const signedIn = Boolean(user);

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topline}>
          <Kicker className={styles.kicker}>行迹 · COLLAB</Kicker>
          {signedIn && trips ? <span className={styles.count}>{trips.length} 份协作</span> : null}
        </div>

        <header className={styles.header}>
          <h1 className={styles.title}>协同</h1>
          <p className={styles.lede}>
            和别人一起规划的行程都在这里，改动实时同步。这里只列出别人共享给你的行程，你自己创建的仍在「行程」里。
          </p>
        </header>

        {!signedIn ? (
          <section className={styles.guestCard} aria-labelledby="collab-guest-title">
            <Kicker className={styles.kicker}>未登录</Kicker>
            <h2 id="collab-guest-title" className={styles.guestTitle}>
              登录后查看协作行程
            </h2>
            <p className={styles.guestBody}>
              别人共享给你的行程会在登录后出现在这里；你的改动也要登录后才能同步给同行的人。
            </p>
            <div className={styles.guestActions}>
              <Button onClick={() => openAuth('login')}>登录 / 注册</Button>
            </div>
          </section>
        ) : error && trips === null ? (
          <ErrorState
            title="协作行程暂时没有取到"
            body={error}
            retryLabel="重新加载"
            onRetry={() => setReloadKey(key => key + 1)}
          />
        ) : trips === null ? (
          <div className={styles.rows} role="status" aria-live="polite" aria-label="正在加载协作行程">
            <Skeleton className={styles.skeletonRow} />
            <Skeleton className={styles.skeletonRow} />
          </div>
        ) : trips.length === 0 ? (
          <EmptyState
            kicker="协同"
            title="还没有协作行程"
            body="向朋友要一个 8 位分享码，或让他们发协作邀请；加入后这里会实时同步。"
            action={<Button onClick={() => navigate('/trips')}>去行程页输入分享码</Button>}
          />
        ) : (
          <section aria-labelledby="collab-list-title">
            <div className={styles.sectionHead}>
              <h2 id="collab-list-title" className={styles.sectionTitle}>
                协作中的行程
              </h2>
              <span className={styles.sectionHint}>每 15 秒同步在线状态</span>
            </div>
            <div className={styles.rows}>
              {trips.map(item => (
                <SharedTripRow
                  key={item.id}
                  share={item}
                  onOpen={share => navigate('/trips/' + share.id)}
                  onLeave={share => {
                    void handleLeave(share);
                  }}
                  leaving={leavingId === item.id}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
