import { useCallback, useEffect, useState } from 'react';
import { parseHash, type Route } from './routes';

export type NavigateOptions = { replace?: boolean };

export type HashRoute = {
  route: Route;
  navigate: (path: string, opts?: NavigateOptions) => void;
  back: () => void;
};

function readHash(): string {
  return typeof window === 'undefined' ? '' : window.location.hash;
}

/** 允许 navigate 接收 '#/trips/7'、'/trips/7' 或 'trips/7'。 */
function toHash(path: string): string {
  if (!path) return '#/';
  if (path.startsWith('#')) return path;
  return path.startsWith('/') ? `#${path}` : `#/${path}`;
}

export function useHashRoute(): HashRoute {
  const [route, setRoute] = useState<Route>(() => parseHash(readHash()));

  useEffect(() => {
    const sync = () => setRoute(parseHash(readHash()));
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    // 首帧到 effect 之间 hash 可能被外部改写，挂载时补一次同步。
    sync();
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);

  const navigate = useCallback((path: string, opts?: NavigateOptions) => {
    const next = toHash(path);
    if (opts?.replace) window.history.replaceState(null, '', next);
    else window.history.pushState(null, '', next);
    // pushState/replaceState 不触发 hashchange：自己维护状态，重复点当前 tab 也能回到初始状态。
    setRoute(parseHash(next));
  }, []);

  const back = useCallback(() => {
    window.history.back();
  }, []);

  return { route, navigate, back };
}
