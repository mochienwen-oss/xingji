const BACK_TARGETS: Record<string, string> = {
  account: '/settings/account',
  profile: '/profile',
  explore: '/explore',
};

/** 条款/隐私页从哪来就回哪去；直接打开或来源未知时回「我的」。 */
export function backTarget(): string {
  try {
    const query = window.location.hash.split('?')[1] ?? '';
    return BACK_TARGETS[new URLSearchParams(query).get('from') ?? ''] ?? '/profile';
  } catch {
    return '/profile';
  }
}

/** 站内互链时继续携带来源，返回按钮不会丢失最初入口。 */
export function originSuffix(): string {
  try {
    const query = window.location.hash.split('?')[1] ?? '';
    const from = new URLSearchParams(query).get('from');
    return from ? '?from=' + encodeURIComponent(from) : '';
  } catch {
    return '';
  }
}
