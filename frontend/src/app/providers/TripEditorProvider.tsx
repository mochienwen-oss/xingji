import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useConfirm } from './ToastProvider';
import { useSession } from './SessionProvider';
import { ApiError, api, message } from '../../lib/api';
import { pollTripVersion } from '../../lib/sync';
import { useTripLive, type LivePresence, type LiveStatus, type LiveTripUpdate } from '../../lib/useTripLive';
import type { Day, Stop, Trip } from '../../types/trip';
import {
  initialTripEditorState,
  reduce,
  type TripEditorAction,
  type TripEditorState,
  type TripUndo,
} from './tripEditorState';

const TRIP_TIMEOUT_MS = 15000;
const POLL_INTERVAL_MS = 10000;
const CONFLICT_TEXT = /已在其他操作中更新|版本|version|重新打开行程/i;
const LEAVE_TEXT = '当前行程还有未保存的修改，确定离开吗？';

function isAccessLost(error: unknown): boolean {
  // 后端对非成员/已删除统一返回 404；403 留给只读角色的未来扩展。
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}

/** 与 TripPage 的文案判断兼容；优先用 409，旧后端/网关丢失 status 时仍能识别。 */
function isVersionConflict(error: unknown): boolean {
  return (error instanceof ApiError && error.status === 409) || CONFLICT_TEXT.test(message(error));
}

// 状态里的 undo 是快照、hook 里的 undo 是动作，同名不能直接相交；
// 快照以 undoSnapshot 暴露，动作保留约定的 undo()。
export type TripEditorContextValue = Omit<TripEditorState, 'undo'> & {
  undoSnapshot: TripUndo | null;
  openTrip: (id: number) => Promise<void>;
  edit: (days: Day[], backlog?: Stop[], options?: { undo?: boolean }) => void;
  save: () => Promise<void>;
  /** AI 对话落库后的版本回执：对齐本地 CAS 版本与轮询基线，避免下一次保存 409。 */
  ackVersion: (version: number) => void;
  /** 改出发日期：只换日期，不动天数与地点；有未保存修改时拒绝。 */
  updateStartDate: (startDate: string | null) => Promise<void>;
  reloadLatest: () => Promise<void>;
  /** 流式对话结果不确定（needsRefresh）时重新拉取服务器版本；有未保存修改时拒绝。 */
  refreshFromServer: () => Promise<boolean>;
  keepMine: () => Promise<void>;
  discardMine: () => Promise<void>;
  recheckAccess: () => Promise<void>;
  undo: () => void;
  /** 路由跳转前调用：dirty 时弹 confirm，返回是否允许离开。 */
  confirmLeave: () => Promise<boolean>;
  /** 实时协同连接状态与在线成员（TripWorkspacePage 头部徽标消费）。 */
  live: { status: LiveStatus; onlineCount: number; presence: LivePresence[] };
  /** 其他成员刚保存了修改：仅在本地 dirty 时由页面展示非阻塞提示条。 */
  remoteUpdate: LiveTripUpdate | null;
  dismissRemoteUpdate: () => void;
};

const TripEditorContext = createContext<TripEditorContextValue | null>(null);

export function TripEditorProvider({ children }: { children: ReactNode }) {
  const confirm = useConfirm();
  // 实时连接必须跟真实登录态绑定：退出登录后行程 state 仍在（页面常驻不卸载），
  // 只看 state.trip 会让旧 socket 一直挂着，服务端和其他成员就会一直看到这位「幽灵在线」用户。
  const { user } = useSession();
  const [state, dispatch] = useReducer(reduce, initialTripEditorState);
  // 连续 dispatch（reloadLatest → keepMine）时，异步方法需要立即读到中间状态。
  const stateRef = useRef(state);
  // 轮询比较的是服务器已知版本，而不是本地正在编辑的 version（CAS 用的那个）。
  const remoteVersionRef = useRef<number | undefined>(state.trip?.version);
  const requestedIdRef = useRef<number | null>(state.trip?.id ?? null);
  const requestTokenRef = useRef(0);
  const stopPollRef = useRef<(() => void) | null>(null);

  const apply = useCallback((action: TripEditorAction) => {
    stateRef.current = reduce(stateRef.current, action);
    dispatch(action);
  }, []);

  // 退出登录/换账号时清空编辑器：页面常驻不卸载，旧行程会一直留在内存里。
  // 只处理「已有账号 → 另一个身份」，首次从游客变登录用户时状态本来就是空的。
  const sessionNameRef = useRef<string | null>(null);
  useEffect(() => {
    const name = user?.username ?? null;
    const previous = sessionNameRef.current;
    sessionNameRef.current = name;
    if (previous !== null && previous !== name) {
      requestTokenRef.current += 1;
      remoteVersionRef.current = undefined;
      requestedIdRef.current = null;
      apply({ type: 'sessionReset' });
    }
  }, [user, apply]);

  const isCurrentRequest = useCallback(
    (tripId: number, token: number) =>
      token === requestTokenRef.current && stateRef.current.trip?.id === tripId,
    [],
  );

  const loseAccess = useCallback(() => {
    remoteVersionRef.current = undefined;
    apply({ type: 'accessLost' });
  }, [apply]);

  const fail = useCallback((error: unknown) => {
    if (isAccessLost(error)) {
      loseAccess();
      return;
    }
    if (isVersionConflict(error)) {
      apply({ type: 'saveConflict' });
      return;
    }
    apply({
      type: 'saveError',
      message: message(error),
      offline: !(error instanceof ApiError),
    });
  }, [apply, loseAccess]);

  const persist = useCallback(async (trip: Trip) => {
    const token = requestTokenRef.current;
    apply({ type: 'saveStart' });
    try {
      const updated = await api<Trip>(`/trips/${trip.id}/days`, {
        method: 'PUT',
        body: JSON.stringify({
          days: trip.days,
          backlog: trip.backlog ?? [],
          version: trip.version,
        }),
      });
      if (!isCurrentRequest(trip.id, token)) return;
      remoteVersionRef.current = updated.version;
      requestedIdRef.current = updated.id;
      apply({ type: 'saveSuccess', trip: updated });
    } catch (error) {
      if (!isCurrentRequest(trip.id, token)) return;
      fail(error);
    }
  }, [apply, fail, isCurrentRequest]);

  const save = useCallback(async () => {
    const current = stateRef.current;
    if (!current.trip || current.busy || current.accessLost || current.saveConflict) return;
    await persist(current.trip);
  }, [persist]);

  const ackVersion = useCallback((version: number) => {
    // AI 在服务端落库后版本已前进：先同步轮询比较基线，再对齐本地 CAS 版本；旧回执不回退。
    if (remoteVersionRef.current === undefined || version > remoteVersionRef.current) {
      remoteVersionRef.current = version;
    }
    apply({ type: 'ackVersion', version });
  }, [apply]);

  const updateStartDate = useCallback(async (startDate: string | null) => {
    const current = stateRef.current;
    if (!current.trip || current.busy || current.accessLost) return;
    if (current.dirty) throw new Error('请先保存当前修改，再调整出发日期。');
    const token = requestTokenRef.current;
    apply({ type: 'saveStart' });
    try {
      const updated = await api<Trip>(`/trips/${current.trip.id}/start-date`, {
        method: 'PUT',
        body: JSON.stringify({ start_date: startDate, version: current.trip.version }),
      });
      if (!isCurrentRequest(current.trip.id, token)) return;
      remoteVersionRef.current = updated.version;
      apply({ type: 'saveSuccess', trip: updated });
    } catch (error) {
      if (!isCurrentRequest(current.trip.id, token)) return;
      fail(error);
      throw error;
    }
  }, [apply, fail, isCurrentRequest]);

  const reloadLatest = useCallback(async () => {
    const current = stateRef.current;
    if (!current.trip || current.busy || current.accessLost) return;
    const tripId = current.trip.id;
    const token = requestTokenRef.current;
    try {
      const fresh = await api<Trip>(`/trips/${tripId}`, { timeoutMs: TRIP_TIMEOUT_MS });
      if (!isCurrentRequest(tripId, token)) return;
      remoteVersionRef.current = fresh.version;
      // 只设置候选，绝不覆盖本地 trip/dirty。
      apply({ type: 'reloadLatest', trip: fresh });
    } catch (error) {
      if (!isCurrentRequest(tripId, token)) return;
      fail(error);
    }
  }, [apply, fail, isCurrentRequest]);

  const keepMine = useCallback(async () => {
    const current = stateRef.current;
    if (!current.trip || current.busy || current.accessLost) return;
    const tripId = current.trip.id;
    const token = requestTokenRef.current;
    let fresh: Trip;
    try {
      fresh = await api<Trip>(`/trips/${tripId}`, { timeoutMs: TRIP_TIMEOUT_MS });
    } catch (error) {
      if (!isCurrentRequest(tripId, token)) return;
      fail(error);
      return;
    }
    if (!isCurrentRequest(tripId, token)) return;
    remoteVersionRef.current = fresh.version;
    apply({ type: 'reloadLatest', trip: fresh });
    apply({ type: 'keepMine' });
    const mine = stateRef.current.trip;
    if (!mine) return;
    // 保留本地 days/backlog，只换成最新 version 后重试 CAS 保存。
    await persist(mine);
  }, [apply, fail, isCurrentRequest, persist]);

  const discardMine = useCallback(async () => {
    const current = stateRef.current;
    if (!current.trip || current.busy || current.accessLost) return;
    const tripId = current.trip.id;
    const token = requestTokenRef.current;
    try {
      const fresh = await api<Trip>(`/trips/${tripId}`, { timeoutMs: TRIP_TIMEOUT_MS });
      if (!isCurrentRequest(tripId, token)) return;
      remoteVersionRef.current = fresh.version;
      apply({ type: 'reloadLatest', trip: fresh });
      apply({ type: 'discardMine' });
    } catch (error) {
      if (!isCurrentRequest(tripId, token)) return;
      fail(error);
    }
  }, [apply, fail, isCurrentRequest]);

  const recheckAccess = useCallback(async () => {
    const id = requestedIdRef.current ?? stateRef.current.trip?.id;
    if (!id) return;
    const token = requestTokenRef.current;
    try {
      const fresh = await api<Trip>(`/trips/${id}`, { timeoutMs: TRIP_TIMEOUT_MS });
      if (token !== requestTokenRef.current) return;
      remoteVersionRef.current = fresh.version;
      const sameTrip = stateRef.current.trip?.id === fresh.id;
      apply({ type: 'reloadLatest', trip: fresh });
      if (!sameTrip) {
        // openTrip 直接 404（或切到另一段行程后失败）时本地没有这段行程，
        // 恢复访问后直接用服务器版本重建，避免把旧行程的本地修改套到新 id 上。
        apply({ type: 'load', trip: fresh });
      } else if (stateRef.current.dirty) {
        apply({ type: 'keepMine' });
      } else {
        apply({ type: 'discardMine' });
      }
    } catch (error) {
      if (token !== requestTokenRef.current) return;
      const suffix = isAccessLost(error) ? '仍然无法访问这个行程，请稍后再试。' : `仍然无法访问这个行程：${message(error)}`;
      apply({ type: 'accessLost' });
      apply({ type: 'saveError', message: suffix, offline: true });
    }
  }, [apply]);

  const edit = useCallback((days: Day[], backlog?: Stop[], options?: { undo?: boolean }) => {
    apply({ type: 'edit', days, backlog, undo: options?.undo });
  }, [apply]);

  const undoEdit = useCallback(() => {
    apply({ type: 'undo' });
  }, [apply]);

  const openTrip = useCallback(async (id: number) => {
    const current = stateRef.current;
    if (current.trip?.id === id && !current.accessLost) return;
    if (current.dirty && !current.accessLost) {
      const leave = await confirm({
        title: '离开当前行程？',
        body: LEAVE_TEXT,
        confirmLabel: '离开',
        cancelLabel: '继续编辑',
        danger: true,
      });
      if (!leave) return;
    }
    stopPollRef.current?.();
    stopPollRef.current = null;
    requestedIdRef.current = id;
    const token = ++requestTokenRef.current;
    try {
      const fresh = await api<Trip>(`/trips/${id}`, { timeoutMs: TRIP_TIMEOUT_MS });
      if (token !== requestTokenRef.current) return;
      remoteVersionRef.current = fresh.version;
      const previous = stateRef.current;
      if (previous.trip?.id === id && previous.dirty) {
        // 同一行程重新打开（例如 accessLost 后重试）时保留未保存的本地修改。
        apply({ type: 'reloadLatest', trip: fresh });
        apply({ type: 'keepMine' });
      } else {
        apply({ type: 'load', trip: fresh });
      }
    } catch (error) {
      if (token !== requestTokenRef.current) return;
      if (isAccessLost(error)) {
        loseAccess();
        return;
      }
      fail(error);
    }
  }, [apply, fail, loseAccess]);

  const refreshFromServer = useCallback(async (): Promise<boolean> => {
    const current = stateRef.current;
    // 服务器可能已经保存了上一轮对话；本地有未保存修改时不能直接覆盖，交给冲突流程处理。
    if (!current.trip || current.busy || current.dirty) return false;
    const tripId = current.trip.id;
    const token = requestTokenRef.current;
    const fresh = await api<Trip>(`/trips/${tripId}`, { timeoutMs: TRIP_TIMEOUT_MS });
    if (!isCurrentRequest(tripId, token)) return false;
    remoteVersionRef.current = fresh.version;
    requestedIdRef.current = fresh.id;
    apply({ type: 'load', trip: fresh });
    return true;
  }, [apply, isCurrentRequest]);

  const confirmLeave = useCallback(async () => {
    const current = stateRef.current;
    if (!current.dirty || current.accessLost) return true;
    return confirm({
      title: '离开当前行程？',
      body: LEAVE_TEXT,
      confirmLabel: '离开',
      cancelLabel: '继续编辑',
      danger: true,
    });
  }, [confirm]);

  // 实时协同：已登录且行程打开后才连 /live；退出登录立即断开，服务端随即广播新的在线名单。
  const live = useTripLive({
    tripId: state.trip?.id ?? null,
    enabled: Boolean(user) && Boolean(state.trip) && !state.accessLost,
  });
  const [remoteUpdate, setRemoteUpdate] = useState<LiveTripUpdate | null>(null);

  const dismissRemoteUpdate = useCallback(() => setRemoteUpdate(null), []);

  const handleRemoteUpdate = useCallback((update: LiveTripUpdate) => {
    const snapshot = stateRef.current;
    if (!snapshot.trip || snapshot.accessLost) return;
    if (snapshot.dirty) {
      // 本地有未保存修改：不推进本地 CAS 版本，让下一次保存照常触发 409 冲突流程；
      // 只同步轮询比较基线避免冗余拉取，并亮出非阻塞提示条。
      if (remoteVersionRef.current === undefined || update.version > remoteVersionRef.current) {
        remoteVersionRef.current = update.version;
      }
      setRemoteUpdate(update);
      return;
    }
    void (async () => {
      // 干净状态：拉最新行程并直接采用；拉取期间用户开始编辑则退回提示条。
      await reloadLatest();
      const fresh = stateRef.current;
      const candidate = fresh.latest;
      // 拉取被 busy/accessLost 挡下或失败时会留下旧候选：版本不够新就交给冲突/轮询流程。
      if (!candidate || (candidate.version ?? 0) < update.version) return;
      // 正在保存/改日期：其成功响应本身就带回服务器最新内容，这里让位。
      if (fresh.busy) return;
      if (fresh.dirty) {
        setRemoteUpdate(update);
        return;
      }
      apply({ type: 'discardMine' });
    })();
  }, [apply, reloadLatest]);

  useEffect(() => {
    if (live.lastUpdate) handleRemoteUpdate(live.lastUpdate);
  }, [live.lastUpdate, handleRemoteUpdate]);

  // WebSocket 的 hello 自带版本号：断线期间可能错过 trip_updated，重连后补拉一次。
  useEffect(() => {
    if (live.status !== 'open' || live.lastVersion === null) return;
    if (remoteVersionRef.current !== undefined && live.lastVersion <= remoteVersionRef.current) return;
    void refreshFromServer();
  }, [live.lastVersion, live.status, refreshFromServer]);

  // 提示条只属于"未保存修改"期间：保存成功/放弃修改/切换行程后自动收起。
  useEffect(() => {
    if (!state.dirty) setRemoteUpdate(null);
  }, [state.dirty]);

  const startPolling = useCallback((id: number) => pollTripVersion(
    id,
    () => remoteVersionRef.current,
    (fresh) => {
      const snapshot = stateRef.current;
      if (snapshot.accessLost) return;
      const trip = fresh as Trip;
      remoteVersionRef.current = trip.version;
      if (snapshot.busy) return;
      if (snapshot.dirty) {
        // 本地有修改时只记候选版本，轮询绝不覆盖本地 trip。
        apply({ type: 'reloadLatest', trip });
        return;
      }
      apply({ type: 'load', trip });
    },
    () => loseAccess(),
    POLL_INTERVAL_MS,
    (status) => apply({ type: 'syncStatus', status }),
  ), [apply, loseAccess]);

  // Provider 挂在 App 层：切底部 tab 只换页面组件，这里不会卸载，编辑状态得以保留。
  // WebSocket 已连接时由服务端推送版本，10s 轮询只在断线时兜底，避免双通道重复拉取。
  const liveOpen = live.status === 'open';
  useEffect(() => {
    const id = state.trip?.id;
    if (!id || state.accessLost || liveOpen) return;
    const stop = startPolling(id);
    stopPollRef.current = stop;
    return () => {
      stop();
      if (stopPollRef.current === stop) stopPollRef.current = null;
    };
  }, [state.trip?.id, state.accessLost, liveOpen, startPolling]);

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      const current = stateRef.current;
      if (!current.dirty || current.accessLost) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  const value = useMemo<TripEditorContextValue>(() => {
    const { undo: undoSnapshot, ...rest } = state;
    return {
      ...rest,
      undoSnapshot,
      openTrip,
      edit,
      save,
      ackVersion,
      updateStartDate,
      reloadLatest,
      refreshFromServer,
      keepMine,
      discardMine,
      recheckAccess,
      undo: undoEdit,
      confirmLeave,
      live: { status: live.status, onlineCount: live.onlineCount, presence: live.presence },
      remoteUpdate,
      dismissRemoteUpdate,
    };
  }, [
    state,
    openTrip,
    edit,
    save,
    ackVersion,
    updateStartDate,
    reloadLatest,
    refreshFromServer,
    keepMine,
    discardMine,
    recheckAccess,
    undoEdit,
    confirmLeave,
    live.status,
    live.onlineCount,
    live.presence,
    remoteUpdate,
    dismissRemoteUpdate,
  ]);

  return <TripEditorContext.Provider value={value}>{children}</TripEditorContext.Provider>;
}

export function useTripEditor(): TripEditorContextValue {
  const value = useContext(TripEditorContext);
  if (!value) throw new Error('useTripEditor 必须在 TripEditorProvider 内使用');
  return value;
}
