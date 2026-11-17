import { useEffect, useState } from 'react';

/** 订阅浏览器在线状态；没有 navigator 时按在线处理，避免误报离线。 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine !== false);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    // 挂载后同步一次，处理首次渲染与真实状态不一致的情况。
    setOnline(navigator.onLine !== false);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);
  return online;
}
