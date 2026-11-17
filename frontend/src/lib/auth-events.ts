/** 新外壳统一接管登录/注册弹层：页面只发意图，不各自实现一套认证 UI。 */
export type AuthIntent = 'login' | 'register' | 'save' | 'settings';

const OPEN_AUTH_EVENT = 'xingji:open-auth';

type OpenAuthDetail = { intent?: AuthIntent };

export function openAuth(intent: AuthIntent = 'login'): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<OpenAuthDetail>(OPEN_AUTH_EVENT, { detail: { intent } }));
}

/** 返回取消订阅函数；App 外壳用它打开统一的认证弹层。 */
export function onOpenAuth(handler: (intent: AuthIntent) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<OpenAuthDetail>).detail;
    handler(detail?.intent ?? 'login');
  };
  window.addEventListener(OPEN_AUTH_EVENT, listener);
  return () => window.removeEventListener(OPEN_AUTH_EVENT, listener);
}
