import { AppShell } from './AppShell';
import { SessionProvider } from './providers/SessionProvider';
import { DraftProvider } from './providers/DraftProvider';
import { TripListProvider } from './providers/TripListProvider';
import { TripEditorProvider } from './providers/TripEditorProvider';
import { ToastProvider } from './providers/ToastProvider';

/**
 * 应用入口只负责组合 Provider 与外壳；路由、页面状态和网络请求都在各自的 Provider/页面里。
 * Provider 顺序有依赖：Session 最先，Draft/TripList 依赖会话；Toast 必须在 TripEditor 外层（confirm 依赖它）。
 */
export function App() {
  return (
    <SessionProvider>
      <DraftProvider>
        <TripListProvider>
          <ToastProvider>
            <TripEditorProvider>
              <AppShell />
            </TripEditorProvider>
          </ToastProvider>
        </TripListProvider>
      </DraftProvider>
    </SessionProvider>
  );
}
