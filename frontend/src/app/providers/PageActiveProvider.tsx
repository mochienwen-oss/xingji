import { createContext, useContext, type ReactNode } from 'react';

/**
 * 页面是否仍在当前路由上。AppShell 会把常驻页面（探索、行程）用 hidden 收起，
 * 页面里的抽屉和弹层据此释放 body 滚动锁，避免隐藏页面继续锁住其他页面。
 * 不在常驻容器里的页面默认 active=true。
 */
const PageActiveContext = createContext(true);

export function PageActiveProvider({ active, children }: { active: boolean; children: ReactNode }) {
  return <PageActiveContext.Provider value={active}>{children}</PageActiveContext.Provider>;
}

export function usePageActive(): boolean {
  return useContext(PageActiveContext);
}
