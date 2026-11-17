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
import { clearAllTodayCaches } from '../../lib/todayCache';
import {
  ApiError,
  login as apiLogin,
  logout as apiLogout,
  me as apiMe,
  register as apiRegister,
  type AuthResponse,
  type MeResponse,
  type RegisterInput,
} from '../../lib/api';
import { broadcastSessionChange, onSessionChange } from '../../lib/sessionChannel';

export type SessionUser = {
  username: string;
  email: string | null;
  emailVerified: boolean;
  needsTerms: boolean;
  needsEmail: boolean;
  /** 最近一次接受服务条款的时间；登录响应用户可能还没有该字段。 */
  acceptedTermsAt: string | null;
};

type SessionContextValue = {
  user: SessionUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<{ emailSent: boolean }>;
  logout: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

/** 后端保持 snake_case；Provider 是唯一把账户响应映射成前端 camelCase 的地方。 */
export function toSessionUser(raw: MeResponse | AuthResponse): SessionUser {
  const email = raw.email ?? null;
  return {
    username: raw.username,
    email,
    emailVerified: raw.email_verified,
    needsTerms: raw.needs_terms,
    needsEmail: raw.needs_email ?? !email,
    acceptedTermsAt: 'accepted_terms_at' in raw ? raw.accepted_terms_at ?? null : null,
  };
}

export function SessionProvider({ children }: { children?: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const userRef = useRef<SessionUser | null>(null);
  // 只接受最新一次 /me 的结果，避免登录后的刷新被挂载时更慢的请求覆盖。
  const requestSeq = useRef(0);

  const applyUser = useCallback((next: SessionUser | null) => {
    userRef.current = next;
    setUser(next);
  }, []);

  const clearUser = useCallback(() => {
    requestSeq.current += 1;
    // 离线快照属于上一个登录账号，退出或会话过期时一并清掉。
    clearAllTodayCaches();
    applyUser(null);
  }, [applyUser]);

  const refresh = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const raw = await apiMe();
      if (seq === requestSeq.current) applyUser(toSessionUser(raw));
    } catch (error) {
      if (seq !== requestSeq.current) return;
      // 401 就是游客态；其它错误也不弹全局错误，等下一次 refresh 再判断。
      if (error instanceof ApiError && error.status === 401) applyUser(null);
      else if (!userRef.current) applyUser(null);
    }
  }, [applyUser]);

  useEffect(() => {
    let active = true;
    void refresh().finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [refresh]);

  useEffect(() => {
    const onUnauthorized = () => clearUser();
    window.addEventListener('xingji:unauthorized', onUnauthorized);
    return () => window.removeEventListener('xingji:unauthorized', onUnauthorized);
  }, [clearUser]);

  // 其他标签页登录/注册/退出会改写共享 cookie；订阅同步信号并重新拉 /me，让本页 UI 与真实会话一致。
  // 这里不弹 toast：ToastProvider 挂在 SessionProvider 内层（见 App.tsx），这一层拿不到也不该由它提示，
  // 跨标签的用户提示交给 AppShell 统一处理。
  useEffect(() => {
    const unsubscribe = onSessionChange(() => {
      // refresh 拿到 401 会自然回到游客态；它本身就是被动同步路径，不能再广播，否则标签间互相触发成环。
      void refresh();
    });
    return unsubscribe;
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const raw = await apiLogin({ username, password });
    const next = toSessionUser(raw);
    applyUser(next);
    // 其他标签共享同一份 cookie：广播用户名让它们刷新到同一个账号。
    broadcastSessionChange(next.username);
    await refresh();
  }, [applyUser, refresh]);

  const register = useCallback(async (input: RegisterInput) => {
    const raw = await apiRegister(input);
    const next = toSessionUser(raw);
    applyUser(next);
    // 注册即登录：同样广播，让其他标签同步到新账号。
    broadcastSessionChange(next.username);
    await refresh();
    // 注册成功但邮件服务没配置时后端返回 email_sent=false；交给弹层提示，不能静默当成功。
    return { emailSent: raw.email_sent !== false };
  }, [applyUser, refresh]);

  const logout = useCallback(async () => {
    // 本地会话先清掉：即使退出接口断网，用户也已经处于游客态。
    clearUser();
    // 即使退出接口失败也广播：其他标签重新拉 /me 与真实 cookie 对齐（cookie 若仍在会回到登录态）。
    broadcastSessionChange(null);
    try {
      await apiLogout();
    } catch {
      // 退出接口失败不影响本地登出。
    }
  }, [clearUser]);

  const value = useMemo<SessionContextValue>(
    () => ({ user, loading, refresh, login, register, logout }),
    [user, loading, refresh, login, register, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession 必须在 SessionProvider 内使用');
  return context;
}
