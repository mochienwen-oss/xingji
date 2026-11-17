const DEFAULT_TIMEOUT_MS = 25000;

export type ApiOptions = RequestInit & { timeoutMs?: number };

/** 账户相关请求只需要控制超时与取消，不允许覆盖方法和请求体。 */
export type AccountOptions = { timeoutMs?: number; signal?: AbortSignal };

/** 这些路径的 401 表示账号或凭据错误，不广播「会话失效」，避免清空未保存的行程。 */
const AUTH_PATH = /^\/(?:login|register)(?:$|[/?])/;
const CREDENTIAL_401_PATHS = new Set([
  '/account',          // 注销：密码错误
  '/account/email',    // 修改邮箱：密码错误
  '/account/password', // 修改密码：当前密码错误
]);
function isCredentialError(url: string) {
  return AUTH_PATH.test(url) || CREDENTIAL_401_PATHS.has(url);
}

export class ApiError extends Error {
  readonly status: number;
  constructor(text: string, status: number) {
    super(text);
    this.name = 'ApiError';
    this.status = status;
  }
}

const FIELD_LABELS: Record<string, string> = {
  city: '城市',
  days: '天数',
  start_date: '出发日期',
  transport: '交通方式',
  budget: '预算',
  travelers: '同行人数',
  title: '标题',
  username: '账号',
  password: '密码',
  email: '邮箱',
  new_password: '新密码',
  current_password: '当前密码',
  accept_terms: '服务条款',
  identifier: '账号或邮箱',
  token: '链接',
  confirm: '确认文字',
};

/** FastAPI 的 422 是字段数组，取第一条映射成用户能看懂的一句话。 */
function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (!Array.isArray(detail)) return '';
  const first = detail.find((item) => item && typeof item === 'object') as
    | { loc?: unknown; msg?: string }
    | undefined;
  if (!first) return '';
  const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : '';
  if (field && FIELD_LABELS[field]) return `${FIELD_LABELS[field]}填写有误，请检查后重试。`;
  return '填写内容有误，请检查后重试。';
}

export async function api<T>(url: string, options: ApiOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...init } = options;
  const controller = new AbortController();
  let timedOut = false;
  const timer = timeoutMs > 0
    ? window.setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs)
    : 0;
  const forwardAbort = () => controller.abort();
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener('abort', forwardAbort);
  }
  try {
    const r = await fetch('/api' + url, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init.headers },
      signal: controller.signal,
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({})) as { detail?: unknown };
      const detail = detailText(body.detail);
      if (r.status === 401) {
        if (!isCredentialError(url)) window.dispatchEvent(new CustomEvent('xingji:unauthorized'));
        throw new ApiError(detail || '登录已过期，请重新登录', r.status);
      }
      if (r.status === 429) throw new ApiError(detail || '操作太频繁，请稍后再试', r.status);
      throw new ApiError(detail || '请求失败，请检查输入。', r.status);
    }
    if (r.status === 204) return undefined as T;
    const text = await r.text();
    return (text ? JSON.parse(text) : undefined) as T;
  } catch (error) {
    if (timedOut) throw new Error('请求超时，请检查网络后重试');
    if (error instanceof TypeError) throw new Error('网络不可用，请检查连接');
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
    callerSignal?.removeEventListener('abort', forwardAbort);
  }
}

export type MeResponse = {
  username: string;
  email: string | null;
  email_verified: boolean;
  needs_terms: boolean;
  needs_email: boolean;
  accepted_terms_at: string | null;
};

/** 登录响应的 needs_email 可能省略；注册响应还会带 email_sent。 */
export type AuthResponse = {
  username: string;
  email: string | null;
  email_verified: boolean;
  needs_terms: boolean;
  needs_email?: boolean;
  email_sent?: boolean;
};

export type RegisterInput = {
  username: string;
  password: string;
  email: string;
  accept_terms: boolean;
};

export type LoginInput = { username: string; password: string };
export type ResetPasswordInput = { token: string; new_password: string };
export type ChangeEmailInput = { email: string; password: string };
export type ChangePasswordInput = { current_password: string; new_password: string };
export type DeleteAccountInput = { password: string; confirm: '注销' };

export function me(options: AccountOptions = {}) {
  return api<MeResponse>('/me', options);
}

export function login(input: LoginInput, options: AccountOptions = {}) {
  return api<AuthResponse>('/login', { ...options, method: 'POST', body: JSON.stringify(input) });
}

export function register(input: RegisterInput, options: AccountOptions = {}) {
  return api<AuthResponse>('/register', { ...options, method: 'POST', body: JSON.stringify(input) });
}

export async function logout(options: AccountOptions = {}): Promise<void> {
  await api<{ ok: boolean }>('/logout', { ...options, method: 'POST' });
}

export function forgotPassword(identifier: string, options: AccountOptions = {}) {
  return api<{ ok: true }>('/account/password/forgot', {
    ...options,
    method: 'POST',
    body: JSON.stringify({ identifier }),
  });
}

export function resetPassword(input: ResetPasswordInput, options: AccountOptions = {}) {
  return api<{ ok: true }>('/account/password/reset', {
    ...options,
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function verifyEmail(token: string, options: AccountOptions = {}) {
  return api<{ ok: true; email: string; kind: string }>('/account/verify-email', {
    ...options,
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}

export function changeEmail(input: ChangeEmailInput, options: AccountOptions = {}) {
  return api<{ pending_email: string; email_sent: boolean }>('/account/email', {
    ...options,
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function resendEmail(options: AccountOptions = {}) {
  return api<{ email_sent: boolean; pending_email?: string }>('/account/email/resend', {
    ...options,
    method: 'POST',
  });
}

export function changePassword(input: ChangePasswordInput, options: AccountOptions = {}) {
  return api<{ ok: true }>('/account/password', {
    ...options,
    method: 'POST',
    body: JSON.stringify(input),
  });
}

/** AI 长期记忆开关：关闭后 Harness 不读取也不写入。 */
export function getMemoryPreference(options: AccountOptions = {}) {
  return api<{ enabled: boolean }>('/account/memory', options);
}

export function setMemoryPreference(enabled: boolean, options: AccountOptions = {}) {
  return api<{ enabled: boolean }>('/account/memory', {
    ...options,
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });
}

export function acceptTerms(options: AccountOptions = {}) {
  return api<{ accepted_terms_at: string }>('/account/terms', { ...options, method: 'POST' });
}

export function deleteAccount(input: DeleteAccountInput, options: AccountOptions = {}) {
  return api<{ ok: true }>('/account', {
    ...options,
    method: 'DELETE',
    body: JSON.stringify(input),
  });
}

export function message(e: unknown) {
  return e instanceof Error ? e.message : '请求失败，请稍后再试。';
}
export function dateText(s: string) {
  return s
    ? new Date(s).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '未知';
}
