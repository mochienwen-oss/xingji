import { useEffect, useRef, useState } from 'react';
import { useHashRoute } from '../app/routing/useHashRoute';
import type { TripsTab } from '../app/routing/routes';
import { useSession } from '../app/providers/SessionProvider';
import { useTripList } from '../app/providers/TripListProvider';
import { useConfirm, useToast } from '../app/providers/ToastProvider';
import { api, ApiError, message } from '../lib/api';
import { openAuth } from '../lib/auth-events';
import { markForkDatePrompt } from '../lib/forkPrompt';
import type { PlazaTrip, TripSummary } from '../types/trip';
import { TrashIcon } from '../components/icons';
import { Button } from '../components/ui/Button';
import { Chip } from '../components/ui/Chip';
import { Dialog } from '../components/ui/Dialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { SegmentedControl } from '../components/ui/SegmentedControl';
import { Skeleton } from '../components/ui/Skeleton';
import { TextField } from '../components/ui/TextField';
import { ReportDialog } from '../components/ReportDialog';
import { PlazaCard } from '../components/trips/PlazaCard';
import { RecycleBin } from '../components/trips/RecycleBin';
import { TripCard, type TripCardAction } from '../components/trips/TripCard';
import { TripsEmptyState } from '../components/trips/TripsEmptyState';
import styles from './TripsPage.module.css';

type TripFilter = 'all' | 'dated' | 'undated';

const TAB_OPTIONS: ReadonlyArray<{ value: TripsTab; label: string }> = [
  { value: 'mine', label: '我的' },
  { value: 'plaza', label: '广场' },
];

const TAB_TITLES: Record<TripsTab, string> = {
  mine: '我的行程',
  plaza: '广场',
};

const TAB_INTROS: Record<TripsTab, string> = {
  mine: '自己走过的路，都收在这里。',
  plaza: '别人公开的路线，复制一份就能改。',
};

const FILTERS: ReadonlyArray<{ value: TripFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'dated', label: '有日期' },
  { value: 'undated', label: '待定' },
];

const SIGN_IN_COPY: Record<TripsTab, { title: string; body: string }> = {
  mine: {
    title: '登录后管理你的行程',
    body: '行程存在账号里：随时接着改、分享给同行的人，删错了也能在 7 天内找回。',
  },
  plaza: {
    title: '登录后逛广场',
    body: '广场里是其他旅行者公开的路线，登录后可以复制成自己的行程。',
  },
};

const PLAZA_TTL_MS = 60_000;
let plazaCache: { at: number; user: string; trips: PlazaTrip[] } | null = null;

function matchesFilter(trip: TripSummary, filter: TripFilter): boolean {
  if (filter === 'all') return true;
  const dated = Boolean(trip.request?.start_date);
  return filter === 'dated' ? dated : !dated;
}

/** 分享码加入失败：404 是码失效、422 是格式问题，其余透出服务端 detail，网络错误给固定文案。 */
function joinErrorMessage(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (reason.status === 404) return '分享码无效或已停用，请向朋友确认。';
    if (reason.status === 422) return '请输入 8 位分享码';
    return message(reason);
  }
  return '网络异常，请稍后重试';
}

function TripsSkeleton() {
  return (
    <div className={styles.grid} role="status" aria-label="正在加载行程">
      {[0, 1, 2].map(item => (
        <div key={item} className={styles.skeletonCard} aria-hidden="true">
          <Skeleton className={styles.skeletonCover} />
          <Skeleton className={styles.skeletonTitle} />
          <Skeleton className={styles.skeletonMeta} />
        </div>
      ))}
    </div>
  );
}

function SignInCard({ tab }: { tab: TripsTab }) {
  const copy = SIGN_IN_COPY[tab];
  return (
    <section className={styles.auth} aria-labelledby="trips-auth-title">
      <p className={styles.authKicker}>未登录</p>
      <h2 className={styles.authTitle} id="trips-auth-title">
        {copy.title}
      </h2>
      <p className={styles.authBody}>{copy.body}</p>
      <Button onClick={() => openAuth('login')}>登录</Button>
    </section>
  );
}

export function TripsPage({ tab }: { tab: TripsTab }) {
  const { navigate } = useHashRoute();
  const { user, loading: sessionLoading } = useSession();
  const { trips, deleted, loading, error, refresh, restore } = useTripList();
  const { toast } = useToast();
  const confirm = useConfirm();

  const [filter, setFilter] = useState<TripFilter>('all');
  const [binOpen, setBinOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<TripSummary | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [renameError, setRenameError] = useState('');
  const [renameBusy, setRenameBusy] = useState(false);
  const [joinOpen, setJoinOpen] = useState(false);
  const [joinValue, setJoinValue] = useState('');
  const [joinError, setJoinError] = useState('');
  const [joinBusy, setJoinBusy] = useState(false);
  const [plaza, setPlaza] = useState<PlazaTrip[] | null>(null);
  const [plazaError, setPlazaError] = useState('');
  const [plazaRetry, setPlazaRetry] = useState(0);
  const [forkBusy, setForkBusy] = useState(false);
  const [reportTarget, setReportTarget] = useState<PlazaTrip | null>(null);
  const pendingRestore = useRef<number | null>(null);

  const username = user?.username ?? null;
  const visibleTrips = trips.filter(trip => matchesFilter(trip, filter));

  useEffect(() => {
    if (tab !== 'plaza' || sessionLoading) return;
    // P1-7：广场是公开数据，游客也直接拉取；登录只影响「复制到我的行程」。
    let active = true;
    const viewer = username ?? '';
    const cached = plazaCache && plazaCache.user === viewer ? plazaCache : null;
    if (cached) setPlaza(cached.trips);
    else setPlaza(null);
    if (cached && plazaRetry === 0 && Date.now() - cached.at < PLAZA_TTL_MS) return;
    setPlazaError('');
    api<{ trips: PlazaTrip[] }>('/plaza')
      .then(result => {
        if (!active) return;
        plazaCache = { at: Date.now(), user: viewer, trips: result.trips };
        setPlaza(result.trips);
      })
      .catch(reason => {
        if (!active) return;
        if (!cached) setPlazaError(message(reason));
      });
    return () => {
      active = false;
    };
  }, [tab, username, sessionLoading, plazaRetry]);

  // 每次进入「我的行程」都拉最新列表：探索页新保存的行程不再被 60s 会话缓存挡住。
  useEffect(() => {
    if (tab !== 'mine' || !username || sessionLoading) return;
    void refresh();
  }, [tab, username, sessionLoading, refresh]);

  // restore() 在 provider 内会吞掉错误，只能等列表刷新结束后再判断结果，避免失败也弹成功提示。
  useEffect(() => {
    if (pendingRestore.current === null || loading) return;
    pendingRestore.current = null;
    if (error) toast(error, 'error');
    else toast('已恢复到我的行程。', 'success');
  }, [loading, error, deleted, toast]);

  const goTab = (next: TripsTab) => {
    if (next === tab) return;
    navigate('/trips?tab=' + next, { replace: true });
  };

  const goExplore = () => navigate('/explore');

  const openTrip = (trip: TripSummary) => navigate('/trips/' + trip.id);

  const startRename = (trip: TripSummary) => {
    setRenameTarget(trip);
    setRenameValue(trip.title ?? '');
    setRenameError('');
  };

  const closeRename = () => {
    if (renameBusy) return;
    setRenameTarget(null);
    setRenameError('');
  };

  const saveRename = async () => {
    const target = renameTarget;
    if (!target || renameBusy) return;
    const title = renameValue.trim();
    if (!title) {
      setRenameError('给行程起个名字');
      return;
    }
    setRenameBusy(true);
    try {
      await api<{ id: number; title: string }>('/trips/' + target.id, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      await refresh();
      setRenameTarget(null);
      toast('已重命名。', 'success');
    } catch (reason) {
      setRenameError(message(reason));
    } finally {
      setRenameBusy(false);
    }
  };

  const openJoinDialog = () => {
    if (!user) {
      openAuth('login');
      return;
    }
    setJoinValue('');
    setJoinError('');
    setJoinOpen(true);
  };

  const closeJoin = () => {
    if (joinBusy) return;
    setJoinOpen(false);
    setJoinError('');
  };

  const submitJoinCode = async () => {
    if (joinBusy) return;
    if (joinValue.length !== 8) {
      setJoinError('请输入 8 位分享码');
      return;
    }
    setJoinBusy(true);
    setJoinError('');
    try {
      const result = await api<{ trip_id: number; title: string | null; already_member: boolean }>(
        '/trips/join',
        { method: 'POST', body: JSON.stringify({ code: joinValue }) },
      );
      setJoinOpen(false);
      await refresh();
      toast('已加入「' + (result.title ?? '协作行程') + '」', 'success');
      navigate('/trips/' + result.trip_id);
    } catch (reason) {
      setJoinError(joinErrorMessage(reason));
    } finally {
      setJoinBusy(false);
    }
  };

  const removeTrip = async (trip: TripSummary) => {
    const collaborators = trip.collaborator_count ?? 0;
    const confirmed = await confirm({
      title: '删除这段行程？',
      body:
        collaborators > 0
          ? '删除后 7 天内可以在回收站恢复。这份行程有 ' +
            collaborators +
            ' 位协作者，删除后他们会同时失去访问。'
          : '删除后 7 天内可以在回收站恢复，之后会永久清除。',
      confirmLabel: '删除',
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api<{ ok: boolean }>('/trips/' + trip.id, { method: 'DELETE' });
      await refresh();
      toast('已移到回收站，7 天内可以恢复。', 'success');
    } catch (reason) {
      toast(message(reason), 'error');
    }
  };

  const restoreTrip = async (id: number) => {
    pendingRestore.current = id;
    await restore(id);
  };

  const askFork = async (trip: PlazaTrip) => {
    if (!user) {
      openAuth('login');
      return;
    }
    if (forkBusy) return;
    const confirmed = await confirm({
      title: '复制到我的行程？',
      body: '会复制路线、地点和天数，不复制原作者的对话。复制后这份行程归你，可以随意改。',
      confirmLabel: '复制一份',
    });
    if (!confirmed) return;
    setForkBusy(true);
    try {
      const created = await api<{ id: number }>('/plaza/' + trip.id + '/fork', { method: 'POST' });
      await refresh();
      toast('已复制到我的行程。', 'success');
      // 与分享页 fork 一致：公开副本不带具体日期，落地后引导用户补上自己的出发日期。
      markForkDatePrompt(created.id);
      navigate('/trips/' + created.id);
    } catch (reason) {
      toast(message(reason), 'error');
    } finally {
      setForkBusy(false);
    }
  };

  const onCardAction = (trip: TripSummary, action: TripCardAction) => {
    if (action === 'rename') startRename(trip);
    else void removeTrip(trip);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <h1 className={styles.pageTitle}>{TAB_TITLES[tab]}</h1>
          <p className={styles.intro}>{TAB_INTROS[tab]}</p>
        </div>
        {tab === 'mine' ? (
          <div className={styles.actions}>
            <Button variant="secondary" onClick={openJoinDialog}>
              输入分享码加入
            </Button>
            {deleted.length > 0 ? (
              <Button
                variant="text"
                className={styles.bin}
                aria-label={'回收站，' + deleted.length + ' 段已删除行程'}
                onClick={() => setBinOpen(true)}
              >
                <TrashIcon size={16} aria-hidden="true" />
                回收站 {deleted.length}
              </Button>
            ) : null}
          </div>
        ) : null}
      </header>

      <SegmentedControl
        className={styles.segmented}
        label="行程视图"
        value={tab}
        options={TAB_OPTIONS}
        onChange={goTab}
      />

      <div className={styles.body}>
        {tab === 'mine' ? (
          sessionLoading ? (
            <TripsSkeleton />
          ) : !user ? (
            <SignInCard tab="mine" />
          ) : error ? (
            <ErrorState body={error} onRetry={() => void refresh()} />
          ) : loading && trips.length === 0 ? (
            <TripsSkeleton />
          ) : trips.length === 0 ? (
            <TripsEmptyState onStart={goExplore} onPickCity={() => goExplore()} />
          ) : (
            <>
              <div className={styles.filters} role="group" aria-label="按日期筛选">
                {FILTERS.map(item => (
                  <Chip
                    key={item.value}
                    selected={filter === item.value}
                    onClick={() => setFilter(item.value)}
                  >
                    {item.label}
                  </Chip>
                ))}
              </div>
              {visibleTrips.length === 0 ? (
                <div className={styles.filterEmpty}>
                  <p>这个筛选下还没有行程。</p>
                  <Button variant="text" onClick={() => setFilter('all')}>
                    显示全部
                  </Button>
                </div>
              ) : (
                <div className={styles.grid}>
                  {visibleTrips.map(trip => (
                    <TripCard key={trip.id} trip={trip} onOpen={openTrip} onAction={onCardAction} />
                  ))}
                </div>
              )}
            </>
          )
        ) : null}

        {tab === 'plaza' ? (
          sessionLoading ? (
            <TripsSkeleton />
          ) : plazaError && !plaza ? (
            <ErrorState body={plazaError} onRetry={() => setPlazaRetry(count => count + 1)} />
          ) : !plaza ? (
            <TripsSkeleton />
          ) : plaza.length === 0 ? (
            <EmptyState
              kicker="广场"
              title="广场还很安静"
              body="等有人公开自己的路线，这里就会热闹起来。"
              action={<Button onClick={goExplore}>去规划一条</Button>}
            />
          ) : (
            <div className={styles.plazaGrid}>
              {plaza.map(trip => (
                <PlazaCard key={trip.id} trip={trip} onFork={askFork} onReport={setReportTarget} />
              ))}
            </div>
          )
        ) : null}

      </div>

      <ReportDialog
        open={reportTarget !== null}
        target={reportTarget ? { kind: 'trip', id: reportTarget.id } : null}
        onClose={() => setReportTarget(null)}
      />

      <RecycleBin
        open={binOpen}
        items={deleted}
        onRestore={id => void restoreTrip(id)}
        onClose={() => setBinOpen(false)}
      />

      <Dialog
        open={renameTarget !== null}
        onClose={closeRename}
        title="重命名行程"
        busy={renameBusy}
        footer={
          <>
            <Button variant="secondary" onClick={closeRename} disabled={renameBusy}>
              取消
            </Button>
            <Button onClick={() => void saveRename()} loading={renameBusy}>
              保存
            </Button>
          </>
        }
      >
        <TextField
          label="行程名称"
          value={renameValue}
          maxLength={80}
          autoComplete="off"
          error={renameError}
          onChange={event => {
            setRenameValue(event.target.value);
            if (renameError) setRenameError('');
          }}
          onKeyDown={event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            void saveRename();
          }}
        />
      </Dialog>

      <Dialog
        open={joinOpen}
        onClose={closeJoin}
        title="加入协作行程"
        busy={joinBusy}
        footer={
          <>
            <Button variant="secondary" onClick={closeJoin} disabled={joinBusy}>
              取消
            </Button>
            <Button
              onClick={() => void submitJoinCode()}
              loading={joinBusy}
              disabled={joinValue.length < 8}
            >
              加入
            </Button>
          </>
        }
      >
        <p className={styles.dialogNote}>输入朋友给你的 8 位分享码</p>
        <TextField
          label="分享码"
          value={joinValue}
          maxLength={8}
          placeholder="例如 AB3D5F7H"
          autoComplete="off"
          error={joinError}
          onChange={event => {
            setJoinValue(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''));
            if (joinError) setJoinError('');
          }}
          onKeyDown={event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            void submitJoinCode();
          }}
        />
      </Dialog>

    </div>
  );
}
