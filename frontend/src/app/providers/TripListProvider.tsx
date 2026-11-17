import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { api, message } from '../../lib/api';
import type { DeletedTrip, TripSummary } from '../../types/trip';
import { useSession } from './SessionProvider';

const TRIP_CACHE_TTL_MS = 60_000;

export function tripCacheKey(username: string): string {
  return `xingji-trips:${username}`;
}

type TripCache = {
  trips: TripSummary[];
  deleted: DeletedTrip[];
  savedAt: number;
};

type TripListContextValue = {
  trips: TripSummary[];
  deleted: DeletedTrip[];
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
  restore: (id: number) => Promise<void>;
};

const TripListContext = createContext<TripListContextValue | null>(null);

function readCache(username: string): TripCache | null {
  try {
    const raw = window.sessionStorage.getItem(tripCacheKey(username));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<TripCache> | null;
    if (!parsed || typeof parsed !== 'object') return null;
    if (!Array.isArray(parsed.trips) || !Array.isArray(parsed.deleted)) return null;
    if (typeof parsed.savedAt !== 'number') return null;
    if (Date.now() - parsed.savedAt >= TRIP_CACHE_TTL_MS) return null;
    return { trips: parsed.trips, deleted: parsed.deleted, savedAt: parsed.savedAt };
  } catch {
    return null;
  }
}

function writeCache(username: string, trips: TripSummary[], deleted: DeletedTrip[]): void {
  try {
    const payload: TripCache = { trips, deleted, savedAt: Date.now() };
    window.sessionStorage.setItem(tripCacheKey(username), JSON.stringify(payload));
  } catch {
    // 缓存只是加速手段，存储不可用时继续用网络结果。
  }
}

function clearCache(username: string): void {
  try {
    window.sessionStorage.removeItem(tripCacheKey(username));
  } catch {
    // 忽略存储不可用。
  }
}

export function TripListProvider({ children }: { children?: ReactNode }) {
  const { user, loading: sessionLoading } = useSession();
  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [deleted, setDeleted] = useState<DeletedTrip[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const ownerRef = useRef<string | null>(null);
  const initializedRef = useRef(false);
  const requestSeq = useRef(0);

  const load = useCallback(async (owner: string) => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError('');
    try {
      const [tripList, deletedList] = await Promise.all([
        api<TripSummary[]>('/trips'),
        api<DeletedTrip[]>('/trips?deleted=true'),
      ]);
      if (seq !== requestSeq.current || ownerRef.current !== owner) return;
      setTrips(tripList);
      setDeleted(deletedList);
      writeCache(owner, tripList, deletedList);
    } catch (reason) {
      if (seq !== requestSeq.current || ownerRef.current !== owner) return;
      setError(message(reason));
    } finally {
      if (seq === requestSeq.current && ownerRef.current === owner) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sessionLoading) return;
    const nextOwner = user?.username ?? null;
    if (initializedRef.current && ownerRef.current === nextOwner) return;
    initializedRef.current = true;
    const previous = ownerRef.current;
    // 任何切换都作废旧请求；旧账号的缓存也删掉，避免下一次同账号登录复用旧列表。
    requestSeq.current += 1;
    if (previous && previous !== nextOwner) clearCache(previous);
    ownerRef.current = nextOwner;
    setTrips([]);
    setDeleted([]);
    setError('');
    if (!nextOwner) {
      setLoading(false);
      return;
    }
    const cached = readCache(nextOwner);
    if (cached) {
      setTrips(cached.trips);
      setDeleted(cached.deleted);
      setLoading(false);
      return;
    }
    void load(nextOwner);
  }, [user?.username, sessionLoading, load]);

  const refresh = useCallback(async () => {
    const owner = ownerRef.current;
    if (!owner) {
      setTrips([]);
      setDeleted([]);
      setError('');
      setLoading(false);
      return;
    }
    await load(owner);
  }, [load]);

  const restore = useCallback(async (id: number) => {
    const owner = ownerRef.current;
    if (!owner) return;
    try {
      await api(`/trips/${id}/restore`, { method: 'POST' });
      if (ownerRef.current === owner) await load(owner);
    } catch (reason) {
      if (ownerRef.current === owner) setError(message(reason));
    }
  }, [load]);

  const value = useMemo<TripListContextValue>(() => ({
    trips,
    deleted,
    loading,
    error,
    refresh,
    restore,
  }), [trips, deleted, loading, error, refresh, restore]);

  return <TripListContext.Provider value={value}>{children}</TripListContext.Provider>;
}

export function useTripList(): TripListContextValue {
  const context = useContext(TripListContext);
  if (!context) throw new Error('useTripList 必须在 TripListProvider 内使用');
  return context;
}
