import { useEffect, useMemo, useRef, useState } from 'react';
import { useHashRoute } from '../app/routing/useHashRoute';
import { usePageActive } from '../app/providers/PageActiveProvider';
import { useTripEditor } from '../app/providers/TripEditorProvider';
import { api, message } from '../lib/api';
import { useOnline } from '../lib/useOnline';
import { useRetryOnActivate } from '../lib/useRetryOnActivate';
import { finishText, scheduleDay } from '../lib/schedule';
import { todayIndex } from '../lib/today';
import { readTodayCache, saveTodayCache, type CachedToday } from '../lib/todayCache';
import { consumeForkDatePrompt } from '../lib/forkPrompt';
import type { ChatMessage, Collaborator, Day, Place, Stop, Trip, TripMapView } from '../types/trip';
import { BudgetPanel } from '../components/BudgetPanel';
import { GuideImport } from '../components/GuideImport';
import { NearbyPlaces } from '../components/NearbyPlaces';
import { SharePanel } from '../components/SharePanel';
import { AccessLostState } from '../components/trip/AccessLostState';
import { AskAiSheet } from '../components/trip/AskAiSheet';
import { ConflictDialog } from '../components/trip/ConflictDialog';
import { DayTabs } from '../components/trip/DayTabs';
import { PlaceTrustSummary } from '../components/trip/PlaceTrust';
import { TripHealth } from '../components/trip/TripHealth';
import { SaveBar } from '../components/trip/SaveBar';
import { StopDetailSheet } from '../components/trip/StopDetailSheet';
import { Timeline } from '../components/trip/Timeline';
import { TodayCard } from '../components/trip/TodayCard';
import { OfflineToday } from '../components/trip/OfflineToday';
import { AiNotice } from '../components/ui/AiNotice';
import { ErrorState } from '../components/ui/ErrorState';
import { TripHeader, type TripMenuAction } from '../components/trip/TripHeader';
import { TripMapPanel } from '../components/trip/TripMapPanel';
import { dayDateText, reorderDayStops, stopTitle, transportLabel } from '../components/trip/workspace';
import { Button } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { Dialog } from '../components/ui/Dialog';
import { Sheet } from '../components/ui/Sheet';
import { TextField } from '../components/ui/TextField';
import { useConfirm, useToast } from '../app/providers/ToastProvider';
import styles from './TripWorkspacePage.module.css';

type SheetKind = 'members' | 'backlog' | 'budget' | 'nearby' | 'guide' | 'stop' | 'ai' | null;

const MEMBER_ROLES: Record<string, string> = { owner: '创建者', edit: '可编辑', view: '只读' };

function mergedBacklog(trip: Trip): Stop[] {
  return trip.backlog ?? [];
}

function allStopIds(trip: Trip): string[] {
  return [
    ...trip.days.flatMap(day => day.stops.map(stop => stop.place.id)),
    ...mergedBacklog(trip).map(stop => stop.place.id),
  ];
}

/** D3 行程工作台：地图、日期、时间线与保存/冲突状态。 */
export function TripWorkspacePage({ tripId }: { tripId: number }) {
  const { route, navigate, back } = useHashRoute();
  const {
    trip,
    dirty,
    busy,
    accessLost,
    saveConflict,
    syncState,
    latest,
    error,
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
    confirmLeave,
    undo,
    undoSnapshot,
    live,
    remoteUpdate,
    dismissRemoteUpdate,
  } = useTripEditor();
  const { toast } = useToast();
  const confirm = useConfirm();
  const pageActive = usePageActive();

  const [selectedDay, setSelectedDay] = useState(0);
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');
  const [renameError, setRenameError] = useState('');
  const [renameBusy, setRenameBusy] = useState(false);
  const [titleOverride, setTitleOverride] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [collaborators, setCollaborators] = useState<Collaborator[]>([]);
  const [optimizeBusy, setOptimizeBusy] = useState(false);
  const [routeBusyDay, setRouteBusyDay] = useState<number | null>(null);
  const [discardBusy, setDiscardBusy] = useState(false);
  const [conflictBusy, setConflictBusy] = useState(false);
  const [conflictDismissed, setConflictDismissed] = useState(false);
  const [dateOpen, setDateOpen] = useState(false);
  const [dateFromFork, setDateFromFork] = useState(false);
  const [dateDraft, setDateDraft] = useState('');
  const [dateError, setDateError] = useState('');
  const [dateBusy, setDateBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [focusPlace, setFocusPlace] = useState<Place | null>(null);
  const [recheckBusy, setRecheckBusy] = useState(false);
  const [utilityDetent, setUtilityDetent] = useState<'peek' | 'half' | 'full'>('full');
  const [now, setNow] = useState(() => new Date());
  const online = useOnline();
  const [cachedToday, setCachedToday] = useState<CachedToday | null>(null);
  const [cacheRetrying, setCacheRetrying] = useState(false);

  const tripRef = useRef<Trip | null>(trip);
  tripRef.current = trip;
  const saveIntent = useRef(false);
  const mergeIntent = useRef(false);
  const conflictIntent = useRef<'keep' | 'latest' | 'discard' | null>(null);
  const wasDirty = useRef(false);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    void openTrip(tripId);
    // openTrip 由 Provider 保证幂等；这里只按 tripId 触发，避免重复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tripId]);

  // 常驻页面被 hidden 后回到同一个行程时上面的 effect 不会重跑；
  // 重新可见时补一次检查，退出协作后又被分享码加回来的场景才能自己恢复。
  useRetryOnActivate(pageActive, accessLost, recheckAccess);

  // 联网加载失败时，优先展示本机缓存的“今天”，不让整页停在“正在打开行程…”。
  useEffect(() => {
    if (trip?.id === tripId) {
      setCachedToday(null);
      return;
    }
    setCachedToday(readTodayCache(tripId));
  }, [trip?.id, tripId, online, syncState]);

  // 从分享页复制后跳过来：只对刚复制出来的这一条行程提示一次。
  useEffect(() => {
    if (!trip || trip.id !== tripId) return;
    if (!consumeForkDatePrompt(trip.id)) return;
    setDateDraft(trip.request.start_date ?? '');
    setDateFromFork(true);
    setDateError('');
    setDateOpen(true);
  }, [trip, tripId]);

  useEffect(() => {
    setSelectedDay(0);
    setSelectedStopId(null);
    setSheet(null);
    setMapExpanded(false);
    setTitleOverride(null);
    setConflictDismissed(false);
    setFocusPlace(null);
  }, [tripId]);

  useEffect(() => {
    const count = trip?.days.length ?? 0;
    if (count > 0 && selectedDay > count - 1) setSelectedDay(count - 1);
  }, [selectedDay, trip?.days.length]);

  useEffect(() => {
    setMessages(trip?.conversation ? [...trip.conversation] : []);
    // 只在新行程载入时换会话；保存后的 conversation 更新不应该打断正在看的对话。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip?.id]);

  useEffect(() => {
    if (!trip) return;
    let alive = true;
    api<{ members: Collaborator[] }>(`/trips/${trip.id}/collaborators`)
      .then(result => {
        if (alive) setCollaborators(result.members ?? []);
      })
      .catch(() => {
        if (alive) setCollaborators([]);
      });
    return () => {
      alive = false;
    };
  }, [trip?.id]);

  useEffect(() => {
    if (saveIntent.current && !dirty) {
      saveIntent.current = false;
      toast('已保存', 'success');
    }
    if (saveIntent.current && saveConflict) saveIntent.current = false;
  }, [dirty, saveConflict, toast]);

  useEffect(() => {
    if (mergeIntent.current && !dirty && !saveConflict) {
      mergeIntent.current = false;
      toast('已合并并保存', 'success');
    }
    if (mergeIntent.current && saveConflict) mergeIntent.current = false;
  }, [dirty, saveConflict, toast]);

  useEffect(() => {
    if (saveConflict) setConflictDismissed(false);
  }, [saveConflict]);

  useEffect(() => {
    if (!saveConflict && conflictIntent.current) {
      const action = conflictIntent.current;
      conflictIntent.current = null;
      if (action === 'keep') toast('已保留我的修改', 'success');
      if (action === 'latest') toast('已载入服务器最新版本', 'success');
      if (action === 'discard') toast('已放弃未保存的修改', 'info');
    }
  }, [saveConflict, toast]);

  useEffect(() => {
    if (!error || accessLost || saveConflict) return;
    toast(error, 'error');
  }, [error, accessLost, saveConflict, toast]);

  const days = trip?.days ?? [];
  const day: Day | undefined = days[selectedDay];
  const backlog = useMemo(() => (trip ? mergedBacklog(trip) : []), [trip]);
  const today = useMemo(
    () => todayIndex(trip?.request.start_date, days.length, now),
    [trip?.request.start_date, days.length, now],
  );
  const todayDay = today != null ? days[today] : undefined;
  const todaySchedule = useMemo(
    () => (trip && todayDay ? scheduleDay(todayDay, trip.request.transport).stops : []),
    [trip, todayDay],
  );

  // 只有已保存的版本才写缓存，避免把未保存的本地改动当成离线快照。
  useEffect(() => {
    if (!trip || trip.id !== tripId || dirty || today == null || !todayDay) return;
    saveTodayCache(trip, today, todayDay);
  }, [trip, tripId, dirty, today, todayDay]);
  const title = titleOverride ?? trip?.title ?? (trip ? `${trip.request.city}行程` : '行程工作台');
  const startDateText = trip?.request.start_date ? `${dayDateText(0, trip.request.start_date)} 出发` : '设出发日期';
  const schedule = useMemo(
    () => (trip && day ? scheduleDay(day, trip.request.transport) : null),
    [trip, day],
  );
  const trustPlaces = useMemo(
    () => [...days.flatMap(day => day.stops.map(stop => stop.place)), ...backlog.map(stop => stop.place)],
    [days, backlog],
  );
  const tripView = useMemo<TripMapView | null>(() => {
    if (!trip || !day) return null;
    return {
      tripId: trip.id,
      previewKey: trip.created_at,
      days: [day],
      backlog,
      showBacklog: true,
      focusPlace,
    };
  }, [trip, day, backlog, focusPlace]);

  const selectedStopIndex = day?.stops.findIndex(stop => stop.place.id === selectedStopId) ?? -1;
  const selectedStop = selectedStopIndex >= 0 ? day?.stops[selectedStopIndex] ?? null : null;
  const optimizeVisible = (day?.stops.length ?? 0) >= 2;
  const optimizeAvailable = optimizeVisible && !dirty && !busy && !optimizeBusy;
  const editorBusy = busy || discardBusy || conflictBusy;
  const finishTime = schedule ? finishText(schedule.finish, schedule.deadline, schedule.buffer) : null;
  const finish = finishTime ?? (day?.start_time && schedule ? '有路段缺时间，结束时间待补全' : null);
  const finishLate = schedule?.finish != null && schedule.deadline != null && schedule.finish > schedule.deadline;

  async function handleBack() {
    if (!(await confirmLeave())) return;
    if (route.name === 'trip' && route.id === tripId) back();
    else navigate('/trips');
  }

  function openStartDate() {
    setDateDraft(trip?.request.start_date ?? '');
    setDateFromFork(false);
    setDateError('');
    setDateOpen(true);
  }

  async function submitStartDate(value: string | null) {
    if (!trip || dateBusy) return;
    if ((value ?? '') === (trip.request.start_date ?? '')) {
      setDateOpen(false);
      return;
    }
    setDateBusy(true);
    setDateError('');
    try {
      await updateStartDate(value);
      setDateOpen(false);
      setDateFromFork(false);
      toast(value ? '出发日期已更新' : '已清除出发日期', 'success');
    } catch (err: unknown) {
      setDateError(message(err));
    } finally {
      setDateBusy(false);
    }
  }

  function openRename() {
    setRenameDraft(title);
    setRenameError('');
    setRenameOpen(true);
  }

  async function submitRename() {
    if (!trip) return;
    const nextTitle = renameDraft.trim();
    if (!nextTitle) {
      setRenameError('请输入行程名称。');
      return;
    }
    setRenameBusy(true);
    setRenameError('');
    try {
      const result = await api<{ id: number; title: string }>(`/trips/${trip.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: nextTitle }),
      });
      setTitleOverride(result.title);
      setRenameOpen(false);
      toast('标题已更新', 'success');
    } catch (err) {
      setRenameError(message(err));
    } finally {
      setRenameBusy(false);
    }
  }

  async function handleSave() {
    if (!dirty || busy) return;
    saveIntent.current = true;
    await save();
  }

  async function handleDiscard() {
    if (busy || discardBusy) return;
    const ok = await confirm({
      title: '放弃未保存的修改？',
      body: '当前改动会全部丢失，服务器上的版本不会变。',
      confirmLabel: '放弃修改',
      danger: true,
    });
    if (!ok) return;
    setDiscardBusy(true);
    try {
      await discardMine();
    } finally {
      setDiscardBusy(false);
    }
  }

  async function handleOptimize() {
    if (!trip || !day || !optimizeAvailable) return;
    const index = selectedDay;
    setOptimizeBusy(true);
    try {
      const result = await api<{ improved: boolean; day: Day; message: string }>(
        `/trips/${trip.id}/days/${index}/optimize`,
        { method: 'POST' },
      );
      // improved=false 时后端原样返回当天数据（见 route_opt.py），此时不能 edit，
      // 否则会凭空产生一次「未保存修改」并把用户挡在返回列表的确认框里。
      if (result.improved) {
        const current = tripRef.current;
        if (current && current.id === trip.id) {
          const nextDays = current.days.map((item, i) => (i === index ? result.day : item));
          edit(nextDays, current.backlog ?? []);
        }
      }
      toast(result.message || (result.improved ? '已优化这一天的顺序' : '当前顺序已经比较顺路'), result.improved ? 'success' : 'info');
    } catch (err) {
      toast(message(err), 'error');
    } finally {
      setOptimizeBusy(false);
    }
  }

  async function handleRecomputeRoutes() {
    if (!trip || !day || dirty || routeBusyDay !== null) return;
    const index = selectedDay;
    setRouteBusyDay(index);
    try {
      const result = await api<{ day: Day }>(`/trips/${trip.id}/days/${index}/routes`, { method: 'POST' });
      const current = tripRef.current;
      if (current && current.id === trip.id) {
        const nextDays = current.days.map((item, i) => (i === index ? result.day : item));
        edit(nextDays, current.backlog ?? []);
      }
      toast('路线已重新计算', 'success');
    } catch (err) {
      toast(message(err), 'error');
    } finally {
      setRouteBusyDay(current => (current === index ? null : current));
    }
  }

  function setDayStartTime(value: string) {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    if (!current || !currentDay || busy) return;
    if ((currentDay.start_time ?? '') === value) return;
    const nextDays = current.days.map((item, i) =>
      i === selectedDay ? { ...item, start_time: value || null } : item,
    );
    edit(nextDays, current.backlog ?? []);
  }

  function setDayEndTime(value: string) {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    if (!current || !currentDay || busy) return;
    if ((currentDay.end_time ?? '') === value) return;
    const nextDays = current.days.map((item, i) =>
      i === selectedDay ? { ...item, end_time: value || null } : item,
    );
    edit(nextDays, current.backlog ?? []);
  }

  function handleReorder(from: number, to: number) {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    if (!current || !currentDay || busy) return;
    const nextDays = current.days.map((item, i) => (i === selectedDay ? reorderDayStops(item, from, to) : item));
    edit(nextDays, current.backlog ?? []);
  }

  function patchSelectedStop(patch: Partial<Stop>) {
    const current = tripRef.current;
    if (!current || !selectedStopId) return;
    const nextDays = current.days.map((item, i) => {
      if (i !== selectedDay) return item;
      return {
        ...item,
        stops: item.stops.map(stop => (stop.place.id === selectedStopId ? { ...stop, ...patch } : stop)),
      };
    });
    edit(nextDays, current.backlog ?? []);
  }

  function moveSelectedStop(delta: number) {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    if (!current || !currentDay || selectedStopIndex < 0) return;
    const to = selectedStopIndex + delta;
    if (to < 0 || to >= currentDay.stops.length) return;
    const nextDays = current.days.map((item, i) =>
      i === selectedDay ? reorderDayStops(item, selectedStopIndex, to) : item,
    );
    edit(nextDays, current.backlog ?? []);
  }

  function deleteSelectedStop() {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    const stop = currentDay?.stops.find(item => item.place.id === selectedStopId);
    if (!current || !currentDay || !stop) return;
    const nextDays = current.days.map((item, i) =>
      i === selectedDay ? { ...item, stops: item.stops.filter(entry => entry.place.id !== stop.place.id), routes: [] } : item,
    );
    edit(nextDays, current.backlog ?? []);
    setSelectedStopId(null);
    setSheet(null);
    toast(`已移除「${stopTitle(stop)}」`, 'info');
  }

  function addBacklogStop(placeId: string) {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    if (!current || !currentDay) return;
    const stop = (current.backlog ?? []).find(item => item.place.id === placeId);
    if (!stop) return;
    const nextBacklog = (current.backlog ?? []).filter(item => item.place.id !== placeId);
    const nextDays = current.days.map((item, i) =>
      i === selectedDay ? { ...item, stops: [...item.stops, stop], routes: [] } : item,
    );
    edit(nextDays, nextBacklog);
    toast(`已加入第 ${selectedDay + 1} 天`, 'success');
  }

  function addNearby(place: Place, anchorId: string) {
    const current = tripRef.current;
    const currentDay = current?.days[selectedDay];
    if (!current || !currentDay) return;
    if (allStopIds(current).includes(place.id)) {
      toast('这个地点已经在行程或待规划中', 'info');
      return;
    }
    const anchorIndex = currentDay.stops.findIndex(stop => stop.place.id === anchorId);
    const nextStops = [...currentDay.stops];
    nextStops.splice(anchorIndex >= 0 ? anchorIndex + 1 : nextStops.length, 0, {
      place,
      duration: 90,
      reason: '',
    });
    const nextDays = current.days.map((item, i) =>
      i === selectedDay ? { ...item, stops: nextStops, routes: [] } : item,
    );
    edit(nextDays, current.backlog ?? []);
    toast('已加入这一天，保存后会更新路线', 'success');
  }

  function addGuidePlaces(places: Place[]): boolean {
    const current = tripRef.current;
    if (!current || busy) return false;
    const existing = new Set(allStopIds(current));
    const fresh = places.filter(place => !existing.has(place.id));
    if (!fresh.length) {
      toast('所选地点已在行程或待规划中', 'error');
      return false;
    }
    if ((current.backlog?.length ?? 0) + fresh.length > 100) {
      toast('待规划最多保存 100 个地点', 'error');
      return false;
    }
    const nextBacklog = [
      ...(current.backlog ?? []),
      ...fresh.map(place => ({ place, duration: 90, reason: '' })),
    ];
    edit(current.days, nextBacklog);
    toast(`已加入待规划 ${fresh.length} 个地点`, 'success');
    return true;
  }

  async function adoptGuide() {
    // 攻略采纳在服务端整份替换 days/backlog；重新拉取服务器版本并丢弃本地空改动，
    // 避免沿用旧 version 导致下一次 CAS 保存冲突。
    await discardMine();
    setSheet(null);
    toast('已采纳攻略并载入最新行程', 'success');
  }

  async function handleAiSuggestion(nextDays: Day[], nextBacklog: Stop[]) {
    if (dirty) {
      const ok = await confirm({
        title: '应用 AI 建议会替换当前修改',
        body: '这段行程还有未保存的修改。继续应用会用 AI 建议覆盖你本地的时间线。',
        confirmLabel: '仍然应用',
        danger: true,
      });
      if (!ok) {
        toast('没有应用 AI 建议', 'info');
        return;
      }
    }
    edit(nextDays, nextBacklog, { undo: true });
    toast('已应用 AI 建议，记得保存', 'success');
  }

  async function handleDelete() {
    if (!trip || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await api(`/trips/${trip.id}`, { method: 'DELETE' });
      setDeleteOpen(false);
      toast('行程已删除，7 天内可恢复', 'success');
      navigate('/trips');
    } catch (err) {
      toast(message(err), 'error');
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleRecheck() {
    setRecheckBusy(true);
    try {
      await recheckAccess();
    } finally {
      setRecheckBusy(false);
    }
  }

  async function handleRetryCached() {
    if (cacheRetrying) return;
    setCacheRetrying(true);
    try {
      await openTrip(tripId);
    } finally {
      setCacheRetrying(false);
    }
  }

  async function handleLoadLatest() {
    const ok = await confirm({
      title: '载入服务器最新版本？',
      body: '你本地未保存的修改会被丢弃，载入后不能恢复。',
      confirmLabel: '载入最新',
      danger: true,
    });
    if (!ok) return;
    setConflictBusy(true);
    conflictIntent.current = 'latest';
    try {
      await reloadLatest();
      await discardMine();
    } finally {
      setConflictBusy(false);
    }
  }

  async function handleKeepMine() {
    setConflictBusy(true);
    conflictIntent.current = 'keep';
    try {
      await keepMine();
    } finally {
      setConflictBusy(false);
    }
  }

  async function handleMerge(days: Day[]) {
    setConflictBusy(true);
    mergeIntent.current = true;
    try {
      // 先把手动合并后的版本放回编辑器，再走「保留我的」换版本重试保存。
      edit(days);
      await keepMine();
    } finally {
      setConflictBusy(false);
    }
  }

  async function handleDiscardConflict() {
    const ok = await confirm({
      title: '放弃本地修改？',
      body: '服务器上的最新版本会覆盖当前时间线。',
      confirmLabel: '放弃修改',
      danger: true,
    });
    if (!ok) return;
    setConflictBusy(true);
    conflictIntent.current = 'discard';
    try {
      await discardMine();
    } finally {
      setConflictBusy(false);
    }
  }

  function handleMenuAction(action: TripMenuAction) {
    if (action === 'delete') {
      setDeleteOpen(true);
      return;
    }
    if (action === 'optimize') {
      void handleOptimize();
      return;
    }
    setSheet(action);
  }

  if (accessLost) {
    return <AccessLostState busy={recheckBusy} onRecheck={() => void handleRecheck()} onBack={() => navigate('/trips')} />;
  }

  if (!trip || trip.id !== tripId) {
    // 只有离线（浏览器断网或请求网络失败）才走本机快照；404/500 仍显示正常加载失败。
    if (cachedToday && (!online || syncState === 'offline')) {
      return (
        <OfflineToday
          cache={cachedToday}
          retrying={cacheRetrying}
          onRetry={() => void handleRetryCached()}
          onBack={() => navigate('/trips')}
        />
      );
    }
    // Provider 在非 404/403 的打开失败时把原文放进 error；否则这里会永远停在加载文案。
    if (error) {
      return (
        <main className={styles.loadingPage}>
          <ErrorState
            title="没能打开这段行程"
            body={error}
            retryLabel="重新打开"
            onRetry={() => void openTrip(tripId)}
          />
        </main>
      );
    }
    return (
      <main className={styles.loadingPage}>
        <p className={styles.loadingText}>正在打开行程…</p>
      </main>
    );
  }

  // 实时协同徽标只在多人在线时出现；title 列出成员名方便确认都有谁在。
  const liveOpen = live.status === 'open' && live.onlineCount > 1;
  const liveNames = live.presence.map((member) => member.username).join('、');

  return (
    <main className={styles.page}>
      <TripHeader
        title={title}
        collaborators={collaborators}
        syncState={syncState}
        optimizeVisible={optimizeVisible}
        optimizeAvailable={optimizeAvailable}
        optimizeBusy={optimizeBusy}
        canManage={trip.is_owner !== false}
        shareSlot={
          <>
            <SharePanel
              tripId={trip.id}
              dirty={dirty}
              isOwner={trip.is_owner}
              isPublic={trip.is_public}
              onLeave={() => navigate('/trips')}
            />
            {liveOpen ? (
              <span className={styles.liveBadge} aria-label="在线协作人数" title={liveNames}>
                <span className={styles.liveDot} aria-hidden="true" />
                {live.onlineCount} 人在线
              </span>
            ) : null}
          </>
        }
        onBack={handleBack}
        onRename={openRename}
        onMembers={() => setSheet('members')}
        onMenuAction={handleMenuAction}
      />

      <div className={styles.content}>
        {remoteUpdate && dirty ? (
          <div className={styles.remoteUpdateBar} role="status">
            <p className={styles.remoteUpdateText}>其他成员刚保存了修改，你现在保存可能提示版本冲突</p>
            <button type="button" className={styles.remoteUpdateClose} aria-label="关闭提示" onClick={dismissRemoteUpdate}>
              ×
            </button>
          </div>
        ) : null}
        {today != null && todayDay ? (
          <TodayCard
            day={todayDay}
            dayIndex={today}
            scheduled={todaySchedule}
            transport={trip.request.transport}
            active={selectedDay === today}
            now={now}
            onSelect={() => {
              setSelectedDay(today);
              setSelectedStopId(null);
              setSheet(null);
              setFocusPlace(null);
            }}
            onAddPlace={() => {
              setSelectedDay(today);
              setSelectedStopId(null);
              setSheet('nearby');
            }}
          />
        ) : null}
        <TripMapPanel
          tripView={tripView}
          city={trip?.request.city ?? ''}
          expanded={mapExpanded}
          dayLabel={`第 ${selectedDay + 1} 天`}
          onToggle={() => setMapExpanded(value => !value)}
        />

        <PlaceTrustSummary places={trustPlaces} className={styles.trustSummary} />
        <TripHealth days={days} backlog={backlog} request={trip.request} className={styles.health} />
        {undoSnapshot ? (
          <div className={styles.undoBar} role="group" aria-label="AI 调整">
            <span>刚刚应用了 AI 调整</span>
            <button
              type="button"
              className={styles.undoButton}
              onClick={() => {
                undo();
                toast('已撤销 AI 调整', 'success');
              }}
            >
              撤销
            </button>
          </div>
        ) : null}

        {day ? (
          <section className={styles.workspace} id="day-panel" role="tabpanel" aria-label={`第 ${selectedDay + 1} 天`}>
            <DayTabs
              days={days}
              selected={selectedDay}
              startDate={trip.request.start_date}
              backlogCount={backlog.length}
              onSelect={index => {
                setSelectedDay(index);
                setSelectedStopId(null);
                setSheet(null);
                setFocusPlace(null);
              }}
              onBacklog={() => setSheet('backlog')}
            />
            {/* 天数已经由 DayTabs 表达，这里只留数量与交通方式，避免重复标题。 */}
            <div className={styles.dayMeta}>
              <span>{day.stops.length} 个地点</span>
              <span title="交通方式在创建行程时确定，当前按行程设置计算">{transportLabel(trip.request.transport)}出行</span>
              <div className={styles.dayTimes}>
                <button
                  type="button"
                  className={styles.dayDate}
                  onClick={openStartDate}
                  disabled={busy}
                  aria-haspopup="dialog"
                  aria-label="设置出发日期"
                >
                  {startDateText}
                </button>
                <label className={styles.dayStart}>
                  <span>出发</span>
                  <input
                    type="time"
                    value={day.start_time ?? ''}
                    onChange={event => setDayStartTime(event.target.value)}
                    disabled={busy}
                    aria-label={`第 ${selectedDay + 1} 天出发时间`}
                  />
                </label>
                <label className={styles.dayStart}>
                  <span>结束</span>
                  <input
                    type="time"
                    value={day.end_time ?? ''}
                    onChange={event => setDayEndTime(event.target.value)}
                    disabled={busy}
                    aria-label={`第 ${selectedDay + 1} 天结束时间`}
                  />
                </label>
              </div>
              {finish ? (
                <span className={finishLate ? `${styles.dayTiming} ${styles.dayTimingLate}` : styles.dayTiming} data-day-timing>
                  {finish}
                </span>
              ) : null}
            </div>
            <Timeline
              day={day}
              dayIndex={selectedDay}
              transport={trip.request.transport}
              dirty={dirty}
              busy={busy}
              routeBusy={routeBusyDay === selectedDay}
              backlogCount={backlog.length}
              scheduled={schedule?.stops ?? []}
              onOpenStop={index => {
                const stop = day.stops[index];
                if (!stop) return;
                setSelectedStopId(stop.place.id);
                setFocusPlace(stop.place);
                setSheet('stop');
              }}
              onReorder={handleReorder}
              onRecomputeRoutes={() => void handleRecomputeRoutes()}
              onOpenBacklog={() => setSheet('backlog')}
              onOpenNearby={() => setSheet('nearby')}
            />
            <AiNotice className={styles.aiNotice}>初始行程由 AI 生成，修改与确认由你完成；出发前请核实地点与时间。</AiNotice>
          </section>
        ) : (
          <section className={styles.workspace}>
            <p className={styles.emptyPage}>这段行程还没有日期。</p>
          </section>
        )}
      </div>

      <SaveBar
        dirty={dirty}
        busy={editorBusy}
        onSave={() => void handleSave()}
        onDiscard={() => void handleDiscard()}
      />

      <button
        type="button"
        className={styles.fab}
        aria-haspopup="dialog"
        aria-label="问 AI"
        onClick={() => setSheet('ai')}
      >
        AI
      </button>

      <Dialog
        open={dateOpen}
        onClose={() => {
          if (!dateBusy) setDateOpen(false);
        }}
        title={dateFromFork ? '先定个出发日期' : '出发日期'}
        busy={dateBusy}
        footer={
          <>
            <Button variant="text" onClick={() => setDateOpen(false)} disabled={dateBusy}>
              取消
            </Button>
            <Button onClick={() => void submitStartDate(dateDraft || null)} loading={dateBusy}>
              保存日期
            </Button>
          </>
        }
      >
        {dateFromFork ? (
          <p className={styles.dateIntro}>
            行程已复制到「我的行程」。先定出发日期，日期会同步到每一天；地点和顺序都保留，之后随时能改。
          </p>
        ) : null}
        <TextField
          label="日期"
          type="date"
          value={dateDraft}
          error={dateError}
          hint="只调整日期，地点、顺序和停留时长保持不变。"
          onChange={event => setDateDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void submitStartDate(dateDraft || null);
            }
          }}
        />
        {trip?.request.start_date ? (
          <Button variant="text" onClick={() => void submitStartDate(null)} disabled={dateBusy}>
            清除日期
          </Button>
        ) : null}
      </Dialog>

      <Dialog
        open={renameOpen}
        onClose={() => {
          if (!renameBusy) setRenameOpen(false);
        }}
        title="重命名行程"
        busy={renameBusy}
        footer={
          <>
            <Button variant="text" onClick={() => setRenameOpen(false)} disabled={renameBusy}>
              取消
            </Button>
            <Button onClick={() => void submitRename()} loading={renameBusy}>
              保存名称
            </Button>
          </>
        }
      >
        <TextField
          label="行程标题"
          value={renameDraft}
          error={renameError}
          maxLength={120}
          autoFocus
          onChange={event => setRenameDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void submitRename();
            }
          }}
        />
      </Dialog>

      <ConfirmDialog
        open={deleteOpen}
        title="删除这段行程？"
        body={
          <>
            删除后行程会进入回收站，7 天内可以恢复；分享链接会立即失效。
            {collaborators.length > 1 ? (
              <strong>
                这份行程还有 {collaborators.length - 1} 位协作者，删除后他们会同时失去访问。
              </strong>
            ) : null}
          </>
        }
        confirmLabel="删除行程"
        danger
        busy={deleteBusy}
        onConfirm={() => void handleDelete()}
        onCancel={() => {
          if (!deleteBusy) setDeleteOpen(false);
        }}
      />

      <ConflictDialog
        open={saveConflict && !conflictDismissed}
        busy={conflictBusy}
        local={trip}
        latest={latest}
        onClose={() => setConflictDismissed(true)}
        onLoadLatest={() => void handleLoadLatest()}
        onKeepMine={() => void handleKeepMine()}
        onDiscard={() => void handleDiscardConflict()}
        onMerge={days => void handleMerge(days)}
      />

      <StopDetailSheet
        open={sheet === 'stop'}
        stop={selectedStop}
        index={selectedStopIndex}
        total={day?.stops.length ?? 0}
        busy={busy}
        transport={trip.request.transport}
        onClose={() => {
          setSheet(null);
          setSelectedStopId(null);
          setFocusPlace(null);
        }}
        onDuration={minutes => patchSelectedStop({ duration: minutes })}
        onFixedTime={(value, nextDay) => patchSelectedStop({ fixed_time: value, fixed_next_day: value ? nextDay : false })}
        onMove={moveSelectedStop}
        onDelete={deleteSelectedStop}
      />

      <Sheet
        open={sheet === 'members'}
        detent="full"
        onDetentChange={() => {}}
        onClose={() => setSheet(null)}
        labelledBy="members-title"
      >
        <div className={styles.membersSheet}>
          <h2 id="members-title" className={styles.sheetTitle}>行程成员</h2>
          <p className={styles.sheetHint}>共 {collaborators.length} 人。邀请、移除成员和公开设置请用右上角「分享」。</p>
          {collaborators.length ? (
            <ul className={styles.memberList}>
              {collaborators.map(member => (
                <li key={member.user_id} className={styles.memberRow}>
                  <span className={styles.memberAvatar} aria-hidden="true">
                    {member.username.slice(0, 1).toUpperCase()}
                  </span>
                  <span className={styles.memberName}>{member.username}</span>
                  <span className={styles.memberRole}>{MEMBER_ROLES[member.role] ?? member.role}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.sheetHint}>还没有读取到成员信息。</p>
          )}
          <Button variant="secondary" onClick={() => setSheet(null)}>关闭</Button>
        </div>
      </Sheet>

      <Sheet
        open={sheet === 'backlog'}
        detent="full"
        onDetentChange={() => {}}
        onClose={() => setSheet(null)}
        labelledBy="backlog-title"
      >
        <div className={styles.backlogSheet}>
          <h2 id="backlog-title" className={styles.sheetTitle}>待规划地点</h2>
          <p className={styles.sheetHint}>先收集想去的地方，再放到第 {selectedDay + 1} 天。</p>
          {backlog.length ? (
            <ul className={styles.backlogList}>
              {backlog.map(stop => (
                <li key={stop.place.id} className={styles.backlogRow}>
                  <div className={styles.backlogInfo}>
                    <strong>{stopTitle(stop)}</strong>
                    <span>{stop.place.address || '地址暂无信息'}</span>
                  </div>
                  <Button variant="secondary" onClick={() => addBacklogStop(stop.place.id)} disabled={busy}>
                    加入第 {selectedDay + 1} 天
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.sheetHint}>待规划里还没有地点。</p>
          )}
          <Button variant="secondary" onClick={() => setSheet(null)}>关闭</Button>
        </div>
      </Sheet>

      <Sheet
        open={sheet === 'budget' || sheet === 'nearby' || sheet === 'guide'}
        detent={utilityDetent}
        onDetentChange={setUtilityDetent}
        onClose={() => setSheet(null)}
        labelledBy="utility-title"
      >
        <div className={styles.utilitySheet}>
          <h2 id="utility-title" className={styles.sheetTitle}>
            {sheet === 'budget' ? '行程预算' : sheet === 'nearby' ? '附近地点' : '导入攻略'}
          </h2>
          {sheet === 'budget' ? (
            <BudgetPanel tripId={trip.id} canEditBudget={trip.is_owner !== false} />
          ) : null}
          {sheet === 'nearby' ? (
            day ? (
              <NearbyPlaces
                tripId={trip.id}
                dayIndex={selectedDay}
                day={day}
                dirty={dirty}
                existingIds={allStopIds(trip)}
                onAdd={addNearby}
              />
            ) : (
              <p className={styles.sheetHint}>当前没有可探索的日期。</p>
            )
          ) : null}
          {sheet === 'guide' ? (
            <GuideImport
              tripId={trip.id}
              city={trip.request.city}
              existingIds={allStopIds(trip)}
              version={trip.version}
              dirty={dirty}
              onAdd={addGuidePlaces}
              onAdopt={() => void adoptGuide()}
            />
          ) : null}
        </div>
      </Sheet>

      <AskAiSheet
        open={sheet === 'ai'}
        trip={trip}
        dirty={dirty}
        messages={messages}
        setMessages={setMessages}
        onClose={() => setSheet(null)}
        onSuggestion={(nextDays, nextBacklog) => void handleAiSuggestion(nextDays, nextBacklog)}
        ackVersion={ackVersion}
        onRefreshTrip={async () => {
          try {
            return await refreshFromServer();
          } catch (err) {
            toast(message(err), 'error');
            return false;
          }
        }}
        onNotify={text => toast(text, 'info')}
        undoAvailable={!!undoSnapshot}
        onUndo={() => {
          undo();
          toast('已撤销 AI 调整', 'success');
        }}
      />
    </main>
  );
}