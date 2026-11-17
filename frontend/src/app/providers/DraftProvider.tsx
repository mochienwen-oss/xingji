import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react';
import { api } from '../../lib/api';
import { PLACE_NAME_UNAVAILABLE } from '../../lib/todayCache';
import type { ChatMessage, Place, PlanRequest } from '../../types/trip';
import { useSession } from './SessionProvider';

export const GUEST_OWNER = 'guest';

/** 草稿落盘防抖：连续输入时只在停顿后写一次 localStorage，避免每个按键都序列化整份草稿。 */
const SAVE_DEBOUNCE_MS = 250;

export function createBlankPlan(): PlanRequest {
  return {
    city: '',
    days: 3,
    start_date: null,
    travelers: 2,
    interests: '',
    pace: '适中',
    budget: '',
    must_visit: '',
    transport: 'transit',
  };
}

/** 游客用 sessionStorage，登录用户用 localStorage；键名只由 owner 决定。 */
export function draftStorageKey(owner: string): string {
  return `xingji-draft:${owner}`;
}

type StoredPlace = { id: string; city?: string };
type StoredDraft = {
  form?: Partial<PlanRequest>;
  messages?: ChatMessage[];
  places?: StoredPlace[];
  /** Harness 的 9 段上下文摘要与轮次：跨刷新保留，换账号时随草稿键隔离。 */
  summary?: Record<string, unknown> | null;
  turnCount?: number;
};
type LoadedDraft = {
  form: PlanRequest;
  messages: ChatMessage[];
  places: Place[];
  ids: string[];
  summary: Record<string, unknown> | null;
  turnCount: number;
};

type DraftContextValue = {
  form: PlanRequest;
  messages: ChatMessage[];
  places: Place[];
  setForm: Dispatch<SetStateAction<PlanRequest>>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  updatePlaces: (change: (current: Place[]) => Place[]) => string;
  clearDraft: () => void;
  ownerKey: string;
  summary: Record<string, unknown> | null;
  turnCount: number;
  setHarness: (next: { summary?: Record<string, unknown> | null; turnCount?: number }) => void;
};

const DraftContext = createContext<DraftContextValue | null>(null);

function storageFor(owner: string): Storage | null {
  try {
    return owner === GUEST_OWNER ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

/** 草稿里是否有值得保留的内容；空壳不算，避免覆盖登录后的真实草稿。 */
function hasDraftContent(raw: string | null): boolean {
  if (!raw) return false;
  try {
    const parsed = JSON.parse(raw) as StoredDraft | null;
    if (!parsed || typeof parsed !== 'object') return false;
    const form = (parsed.form ?? {}) as Partial<PlanRequest>;
    const hasForm = [form.city, form.interests, form.must_visit, form.budget]
      .some((value) => typeof value === 'string' && value.trim().length > 0);
    const hasMessages = Array.isArray(parsed.messages) && parsed.messages.length > 0;
    const hasPlaces = Array.isArray(parsed.places) && parsed.places.length > 0;
    return hasForm || hasMessages || hasPlaces || Boolean(parsed.summary);
  } catch {
    return false;
  }
}

/**
 * 游客草稿存在 sessionStorage，登录后键名会换成用户名。
 * 登录的同一标签页里把游客草稿搬过去，避免用户刚写的内容凭空消失。
 * 已有真实内容的账号草稿优先，不覆盖。
 */
function migrateGuestDraft(nextOwner: string): void {
  if (nextOwner === GUEST_OWNER) return;
  const from = storageFor(GUEST_OWNER);
  const to = storageFor(nextOwner);
  if (!from || !to) return;
  try {
    if (hasDraftContent(to.getItem(draftStorageKey(nextOwner)))) return;
    const raw = from.getItem(draftStorageKey(GUEST_OWNER));
    if (!hasDraftContent(raw) || !raw) return;
    to.setItem(draftStorageKey(nextOwner), raw);
    from.removeItem(draftStorageKey(GUEST_OWNER));
  } catch {
    // 存储不可用或配额满时保持原样，不阻塞登录。
  }
}

function blankDraft(): LoadedDraft {
  return { form: createBlankPlan(), messages: [], places: [], ids: [], summary: null, turnCount: 0 };
}

function readDraft(owner: string): LoadedDraft {
  const storage = storageFor(owner);
  if (!storage) return blankDraft();
  let raw: string | null = null;
  try {
    raw = storage.getItem(draftStorageKey(owner));
  } catch {
    return blankDraft();
  }
  if (!raw) return blankDraft();
  try {
    const parsed = JSON.parse(raw) as StoredDraft | null;
    if (!parsed || typeof parsed !== 'object') return blankDraft();
    const form = parsed.form && typeof parsed.form === 'object'
      ? { ...createBlankPlan(), ...parsed.form }
      : createBlankPlan();
    const messages = Array.isArray(parsed.messages)
      ? parsed.messages.filter((item): item is ChatMessage => Boolean(
        item
        && typeof item === 'object'
        && (item.role === 'user' || item.role === 'assistant')
        && typeof item.content === 'string',
      ))
      : [];
    const saved = (Array.isArray(parsed.places) ? parsed.places : [])
      .filter((item): item is StoredPlace => Boolean(
        item && typeof item === 'object' && typeof item.id === 'string',
      ))
      .slice(0, 60)
      .map((place) => ({ id: place.id, city: typeof place.city === 'string' ? place.city : '' }));
    const cities = new Map(saved.map((place) => [place.id, place.city || '']));
    const ids = saved.map((place) => place.id);
    const summary = parsed.summary && typeof parsed.summary === 'object' && !Array.isArray(parsed.summary)
      ? parsed.summary as Record<string, unknown>
      : null;
    const turnCount = typeof parsed.turnCount === 'number' && Number.isFinite(parsed.turnCount)
      ? Math.max(0, Math.floor(parsed.turnCount))
      : 0;
    return {
      summary,
      turnCount,
      form,
      messages,
      places: ids.map((id) => ({
        id,
        name: PLACE_NAME_UNAVAILABLE,
        address: '',
        location: '',
        opentime: '',
        cost: '',
        source_time: '',
        city: cities.get(id) || '',
        unavailable: true,
      })),
      ids,
    };
  } catch {
    return blankDraft();
  }
}

function writeDraft(
  owner: string,
  draft: {
    form: PlanRequest;
    messages: ChatMessage[];
    places: Place[];
    summary: Record<string, unknown> | null;
    turnCount: number;
  },
): void {
  const storage = storageFor(owner);
  if (!storage) throw new Error('storage unavailable');
  const payload: StoredDraft = {
    form: draft.form,
    messages: draft.messages,
    places: draft.places.map((place) => ({ id: place.id, city: place.city || '' })),
    summary: draft.summary,
    turnCount: draft.turnCount,
  };
  storage.setItem(draftStorageKey(owner), JSON.stringify(payload));
}

export function DraftProvider({ children }: { children?: ReactNode }) {
  const { user, loading: sessionLoading } = useSession();
  const [form, setForm] = useState<PlanRequest>(() => createBlankPlan());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [turnCount, setTurnCount] = useState(0);
  const [ownerKey, setOwnerKey] = useState(GUEST_OWNER);

  const ownerRef = useRef<string | null>(null);
  const loadSeq = useRef(0);
  // clearDraft 已经删掉键，不要让紧接着的空 state 再次把空草稿写回去。
  const skipNextSaveRef = useRef(false);
  // 读出的快照还没真正进入 state 前，不能把上一账号的旧 state 写进新账号的键。
  const hydratingRef = useRef(true);
  // 防抖中的落盘定时器：切换账号/清空草稿时必须取消，避免旧内容写进新键。
  const saveTimerRef = useRef<number | null>(null);
  const formRef = useRef(form);
  const messagesRef = useRef(messages);
  const placesRef = useRef(places);
  const summaryRef = useRef(summary);
  const turnCountRef = useRef(turnCount);
  formRef.current = form;
  messagesRef.current = messages;
  placesRef.current = places;
  summaryRef.current = summary;
  turnCountRef.current = turnCount;

  const loadDetails = useCallback((owner: string, ids: string[], seq: number) => {
    if (!ids.length) return;
    void api<Record<string, Place>>('/places/details', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }).then((found) => {
      if (seq !== loadSeq.current || ownerRef.current !== owner) return;
      setPlaces((current) => current.map((place) => {
        const hit = found[place.id];
        return hit ? { ...hit, city: hit.city || place.city } : place;
      }));
    }).catch(() => {
      // 详情不可用时保留「地点信息暂不可用」占位，不阻塞其他草稿内容。
    });
  }, []);

  useEffect(() => {
    if (sessionLoading) return;
    const nextOwner = user?.username ?? GUEST_OWNER;
    const previousOwner = ownerRef.current;
    if (previousOwner === nextOwner) return;
    // 取消上一个账号还没落盘的防抖写入，否则会按新 owner 的键写旧内容。
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (previousOwner) {
      // 先把内存里的最新草稿落盘，再迁移/换键，避免 state 还没写回存储。
      try {
        writeDraft(previousOwner, {
          form: formRef.current,
          messages: messagesRef.current,
          places: placesRef.current,
          summary: summaryRef.current,
          turnCount: turnCountRef.current,
        });
      } catch {
        // 存储不可用时直接迁移已有内容。
      }
    }
    migrateGuestDraft(nextOwner);
    const seq = ++loadSeq.current;
    hydratingRef.current = true;
    ownerRef.current = nextOwner;
    setOwnerKey(nextOwner);
    const draft = readDraft(nextOwner);
    setForm(draft.form);
    setMessages(draft.messages);
    setPlaces(draft.places);
    setSummary(draft.summary);
    setTurnCount(draft.turnCount);
    loadDetails(nextOwner, draft.ids, seq);
  }, [user?.username, sessionLoading, loadDetails]);

  useEffect(() => {
    if (sessionLoading) return;
    if (hydratingRef.current) {
      // 本次渲染仍是切换前的旧 state；等载入后的下一次渲染再持久化。
      hydratingRef.current = false;
      return;
    }
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false;
      return;
    }
    const owner = ownerRef.current;
    if (!owner) return;
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      if (ownerRef.current !== owner || hydratingRef.current) return;
      try {
        writeDraft(owner, {
          form: formRef.current,
          messages: messagesRef.current,
          places: placesRef.current,
          summary: summaryRef.current,
          turnCount: turnCountRef.current,
        });
      } catch {
        // 存储不可用或配额满时不阻塞规划流程。
      }
    }, SAVE_DEBOUNCE_MS);
    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [form, messages, places, summary, turnCount, ownerKey, sessionLoading]);

  // 卸载时把还在防抖窗口里的最后一次修改补写掉，避免关页面丢草稿。
  useEffect(() => () => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    const owner = ownerRef.current;
    if (!owner || hydratingRef.current) return;
    try {
      writeDraft(owner, {
        form: formRef.current,
        messages: messagesRef.current,
        places: placesRef.current,
        summary: summaryRef.current,
        turnCount: turnCountRef.current,
      });
    } catch {
      // 存储不可用时不阻塞卸载。
    }
  }, []);

  const updatePlaces = useCallback((change: (current: Place[]) => Place[]): string => {
    const owner = ownerRef.current;
    if (!owner || hydratingRef.current) return '收藏尚未准备好，请稍后重试。';
    const next = change(placesRef.current);
    try {
      writeDraft(owner, {
        form: formRef.current,
        messages: messagesRef.current,
        places: next,
        summary: summaryRef.current,
        turnCount: turnCountRef.current,
      });
    } catch {
      return '收藏保存失败，请检查浏览器存储权限后重试。';
    }
    placesRef.current = next;
    setPlaces(next);
    return '';
  }, []);

  const clearDraft = useCallback(() => {
    const owner = ownerRef.current;
    if (owner) {
      try {
        storageFor(owner)?.removeItem(draftStorageKey(owner));
      } catch {
        // 清不掉时，下面的空 state 仍会覆盖旧内容。
      }
    }
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    skipNextSaveRef.current = true;
    setForm(createBlankPlan());
    setMessages([]);
    setPlaces([]);
    setSummary(null);
    setTurnCount(0);
  }, []);

  const setHarness = useCallback((next: { summary?: Record<string, unknown> | null; turnCount?: number }) => {
    if (next.summary !== undefined) setSummary(next.summary);
    if (typeof next.turnCount === 'number') setTurnCount(next.turnCount);
  }, []);

  const value = useMemo<DraftContextValue>(() => ({
    form,
    messages,
    places,
    setForm,
    setMessages,
    updatePlaces,
    clearDraft,
    ownerKey,
    summary,
    turnCount,
    setHarness,
  }), [form, messages, places, updatePlaces, clearDraft, ownerKey, summary, turnCount, setHarness]);

  return <DraftContext.Provider value={value}>{children}</DraftContext.Provider>;
}

export function useDraft(): DraftContextValue {
  const context = useContext(DraftContext);
  if (!context) throw new Error('useDraft 必须在 DraftProvider 内使用');
  return context;
}
