export type TripsTab = 'mine' | 'plaza';

export type Route =
  | { name: 'explore' }
  | { name: 'trips'; tab: TripsTab }
  | { name: 'collab' }
  | { name: 'trip'; id: number }
  | { name: 'profile' }
  | { name: 'account' }
  | { name: 'forgot' }
  | { name: 'reset'; token: string }
  | { name: 'verify'; token: string }
  | { name: 'terms' }
  | { name: 'privacy' }
  | { name: 'share'; token: string }
  | { name: 'invite'; token: string }
  | { name: 'notFound'; hash: string };

const LEGACY_LINK = /^#(share|invite|reset|verify)=(.*)$/;
const TABS: TripsTab[] = ['mine', 'plaza'];

function decodeToken(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function tabFrom(value: string | null): TripsTab {
  return TABS.includes(value as TripsTab) ? (value as TripsTab) : 'mine';
}

function idFrom(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/**
 * 解析 window.location.hash。
 * 邮件/邀请链接沿用旧的 #share=、#invite=、#reset=、#verify= 形式，先于 #/ 路径匹配，
 * 避免旧链接在改造后失效；其余走可读 hash 路由。
 */
export function parseHash(input: string): Route {
  const raw = input ?? '';
  const hash = raw.startsWith('#') ? raw : raw ? `#${raw}` : '';
  if (!hash || hash === '#') return { name: 'explore' };

  const legacy = LEGACY_LINK.exec(hash);
  if (legacy) {
    const token = decodeToken(legacy[2]);
    if (token) {
      const name = legacy[1] as 'share' | 'invite' | 'reset' | 'verify';
      return { name, token };
    }
    return { name: 'notFound', hash };
  }

  const [path, query = ''] = hash.slice(1).split('?');
  if (!path.startsWith('/')) return { name: 'notFound', hash };

  const segments = path.split('/').filter(Boolean);
  if (segments.length === 0) return { name: 'explore' };

  const [head, second] = segments;
  switch (head) {
    case 'explore':
      return segments.length === 1 ? { name: 'explore' } : { name: 'notFound', hash };
    case 'collab':
      return segments.length === 1 ? { name: 'collab' } : { name: 'notFound', hash };
    case 'trips': {
      if (segments.length === 1) {
        const tab = new URLSearchParams(query).get('tab');
        // 旧「行程 → 共享」入口已提升为一级「协同」页，老书签/口令直接落到新页面。
        if (tab === 'shared') return { name: 'collab' };
        return { name: 'trips', tab: tabFrom(tab) };
      }
      if (segments.length === 2) {
        const id = idFrom(second);
        return id === null ? { name: 'notFound', hash } : { name: 'trip', id };
      }
      return { name: 'notFound', hash };
    }
    case 'profile':
      return segments.length === 1 ? { name: 'profile' } : { name: 'notFound', hash };
    case 'forgot':
      return segments.length === 1 ? { name: 'forgot' } : { name: 'notFound', hash };
    case 'terms':
      return segments.length === 1 ? { name: 'terms' } : { name: 'notFound', hash };
    case 'privacy':
      return segments.length === 1 ? { name: 'privacy' } : { name: 'notFound', hash };
    case 'settings':
      if (segments.length !== 2) return { name: 'notFound', hash };
      if (second === 'account') return { name: 'account' };
      if (second === 'privacy') return { name: 'privacy' };
      return { name: 'notFound', hash };
    default:
      return { name: 'notFound', hash };
  }
}
