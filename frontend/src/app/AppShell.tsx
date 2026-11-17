import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api, message } from '../lib/api';
import { useOnline } from '../lib/useOnline';
import { onSessionChange } from '../lib/sessionChannel';
import { openAuth, onOpenAuth, type AuthIntent } from '../lib/auth-events';
import { useHashRoute } from './routing/useHashRoute';
import { useSession } from './providers/SessionProvider';
import { PageActiveProvider } from './providers/PageActiveProvider';
import { useVisualViewport } from '../lib/useVisualViewport';
import { useToast } from './providers/ToastProvider';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { BottomNav, type NavTab } from '../components/nav/BottomNav';
import { TopNav } from '../components/nav/TopNav';
import { AuthDialog, type AuthMode } from '../components/account/AuthDialog';
import { ExplorePage } from '../pages/ExplorePage';
import { TripsPage } from '../pages/TripsPage';
import { TripWorkspacePage } from '../pages/TripWorkspacePage';
import { ProfilePage } from '../pages/ProfilePage';
import { CollabPage } from '../pages/CollabPage';
// 低频深链页面按需加载，避免分享页/账户页拖慢探索首页首屏。
const AccountSettingsPage = lazy(() => import('../pages/AccountSettingsPage').then(module => ({ default: module.AccountSettingsPage })));
const ForgotPage = lazy(() => import('../pages/auth/ForgotPage').then(module => ({ default: module.ForgotPage })));
const ResetPage = lazy(() => import('../pages/auth/ResetPage').then(module => ({ default: module.ResetPage })));
const VerifyPage = lazy(() => import('../pages/auth/VerifyPage').then(module => ({ default: module.VerifyPage })));
const TermsPage = lazy(() => import('../pages/auth/TermsPage').then(module => ({ default: module.TermsPage })));
const PrivacyPage = lazy(() => import('../pages/auth/PrivacyPage').then(module => ({ default: module.PrivacyPage })));
const SharedTripPage = lazy(() => import('../pages/SharedTripPage').then(module => ({ default: module.SharedTripPage })));
import styles from './AppShell.module.css';

const TITLES: Record<string, string> = {
  explore: '行迹 · 把想法变成一条路线',
  trips: '我的行程 · 行迹',
  trip: '行程 · 行迹',
  collab: '协同 · 行迹',
  profile: '我的 · 行迹',
  account: '账户与安全 · 行迹',
  forgot: '找回密码 · 行迹',
  reset: '重置密码 · 行迹',
  verify: '验证邮箱 · 行迹',
  terms: '服务条款 · 行迹',
  privacy: '隐私说明 · 行迹',
  share: '只读分享 · 行迹',
  invite: '协作邀请 · 行迹',
  notFound: '页面不存在 · 行迹',
};

const NAV_ROUTES = new Set(['explore', 'trips', 'collab', 'profile']);

function tabFor(name: string): NavTab {
  if (name === 'trips') return 'trips';
  if (name === 'collab') return 'collab';
  if (name === 'profile') return 'profile';
  return 'explore';
}

/** accept 的各失败码分别引导：404 令牌刚被消费（含刷新重放）、409 并发领取、410 过期、422 自己的邀请、503 正在处理。 */
const INVITE_FAILURE_TEXT: Record<number, string> = {
  404: '邀请链接已被使用或已失效。如果你刚接受过邀请，请到「协同」查看这份行程。',
  409: '邀请链接已被使用或已失效，请让行程创建者重新发送。',
  410: '邀请链接已过期，请让行程创建者重新生成邀请。',
  422: '这是你自己发起的邀请，把链接发给同伴后由对方接受。',
  503: '邀请正在被处理，请稍后重试。',
};

function inviteFailureText(reason: unknown) {
  if (reason instanceof ApiError) {
    const text = INVITE_FAILURE_TEXT[reason.status];
    if (text) return text;
  }
  return message(reason);
}

/** 新外壳：唯一的路由出口。页面不接收会话 props，全部从 Provider 取。 */
export function AppShell() {
  const { route, navigate } = useHashRoute();
  const { user, loading } = useSession();
  const { toast } = useToast();
  const online = useOnline();
  useVisualViewport();

  const [auth, setAuth] = useState<{ open: boolean; mode: AuthMode; intent: AuthIntent; notice?: string }>({
    open: false,
    mode: 'login',
    intent: 'login',
  });
  const [restored, setRestored] = useState(false);
  const wasOffline = useRef(false);
  const [invite, setInvite] = useState<{ busy: boolean; error: string; accepted: boolean }>({
    busy: false,
    error: '',
    accepted: false,
  });
  const inviteStarted = useRef('');

  // 401 只在已有登录态时提示；游客启动时的 401 不应弹窗。
  const userRef = useRef(user);
  userRef.current = user;
  useEffect(() => {
    const expire = () => {
      if (!userRef.current) return;
      setAuth({ open: true, mode: 'login', intent: 'login', notice: '登录已过期，请重新登录' });
      toast('登录已过期，请重新登录', 'error');
    };
    window.addEventListener('xingji:unauthorized', expire);
    return () => window.removeEventListener('xingji:unauthorized', expire);
  }, [toast]);

  // 同一浏览器的标签页共享登录 cookie：别的标签换了账号，本页的界面也得跟着换，
  // 否则会停在上一个账号的缓存列表上（用户会误以为「两个号数据串了」）。
  // SessionProvider 只负责重新拉 /me；这里负责告知用户「页面已经切过去了」。
  useEffect(() => onSessionChange(change => {
    const next = change.username;
    const current = userRef.current?.username ?? null;
    if (next === current) return;
    if (next) toast(`另一个标签页已登录「${next}」，本页已同步切换`, 'success');
    else toast('另一个标签页已退出登录，本页已同步。', 'info');
  }), [toast]);

  // 页面只发意图，外壳统一打开登录/注册弹层。
  useEffect(() => onOpenAuth(intent => {
    if (intent === 'settings') {
      if (userRef.current) navigate('/settings/account');
      else setAuth({ open: true, mode: 'login', intent });
      return;
    }
    setAuth({ open: true, mode: intent === 'register' ? 'register' : 'login', intent });
  }), [navigate]);

  useEffect(() => {
    if (!online) {
      wasOffline.current = true;
      setRestored(false);
      return;
    }
    if (!wasOffline.current) return;
    wasOffline.current = false;
    setRestored(true);
    const timer = window.setTimeout(() => setRestored(false), 2400);
    return () => window.clearTimeout(timer);
  }, [online]);

  useEffect(() => {
    document.title = TITLES[route.name] ?? TITLES.notFound;
  }, [route.name]);

  const inviteToken = route.name === 'invite' ? route.token : '';
  // 登录/注册会连续两次替换 user 对象身份（登录响应 + 随后的 /me 刷新）。邀请接受只关心
  // 「是否已登录」：用布尔值进 deps，身份替换既不重启 effect 也不触发 cleanup，避免把
  // 进行中的 accept 作废（P1：结果被丢弃后 busy 永久卡在「正在接受邀请…」）。
  const hasUser = user !== null;
  const acceptInvite = useCallback((token: string) => {
    inviteStarted.current = token;
    setInvite({ busy: true, error: '', accepted: false });
    void api<{ trip_id: number; title: string | null; city: string }>('/collaborators/accept', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }).then(result => {
      // 同一 token 只发一次 accept，结果必须落地；不做 alive 门控，否则 effect 的任何重跑
      // （如登录态变化）都会让 accept 的返回被静默丢弃。
      setInvite({ busy: false, error: '', accepted: true });
      toast('已接受邀请，正在打开行程', 'success');
      navigate(`/trips/${result.trip_id}`, { replace: true });
    }).catch((reason: unknown) => {
      setInvite({ busy: false, error: inviteFailureText(reason), accepted: false });
    });
  }, [navigate, toast]);

  useEffect(() => {
    if (!inviteToken || !hasUser) return;
    if (inviteStarted.current === inviteToken) return;
    acceptInvite(inviteToken);
  }, [inviteToken, hasUser, acceptInvite]);

  function handleAuthSuccess() {
    if (auth.intent === 'save') toast('登录成功，可以保存这条行程了', 'success');
    if (auth.intent === 'register') toast('账号已创建，请去邮箱完成验证', 'success');
  }

  const showNav = NAV_ROUTES.has(route.name);
  const navClass = showNav ? styles.withNav : '';
  const routeKey = JSON.stringify(route);
  const mainRef = useRef<HTMLElement>(null);
  const firstRoute = useRef(true);

  // 模型回复要跨页面继续：探索页和当前行程页常驻挂载，离开路由时只 hidden。
  // 不卸载组件，usePlanningSession/TravelChat 的卸载 abort 就不会触发。
  const activeExplore = route.name === 'explore';
  const activeTripId = route.name === 'trip' ? route.id : null;
  const [exploreMounted, setExploreMounted] = useState(activeExplore);
  const [tripHostId, setTripHostId] = useState<number | null>(activeTripId);
  if (activeExplore && !exploreMounted) setExploreMounted(true);
  // 切到另一段行程时换一个 key 重新挂载；回到列表/我的时保留当前行程。
  if (activeTripId !== null && activeTripId !== tripHostId) setTripHostId(activeTripId);

  // 单页应用换路由时浏览器不会重置滚动位置，这里显式回顶并把焦点交给主区域，
  // 让键盘和读屏用户知道页面已经切换。
  useEffect(() => {
    if (firstRoute.current) { firstRoute.current = false; return; }
    window.scrollTo(0, 0);
    mainRef.current?.focus({ preventScroll: true });
  }, [routeKey]);

  // 常驻页面从 hidden 恢复时，地图容器尺寸才重新可测；高德的 resizeEnable
  // 监听 window resize，这里在布局稳定后补一次，避免地图保持 0x0。
  useEffect(() => {
    if (route.name !== 'explore' && route.name !== 'trip') return;
    let second = 0;
    const first = window.requestAnimationFrame(() => {
      second = window.requestAnimationFrame(() => {
        window.dispatchEvent(new Event('resize'));
      });
    });
    return () => {
      window.cancelAnimationFrame(first);
      if (second) window.cancelAnimationFrame(second);
    };
  }, [route.name, activeTripId, routeKey]);

  function renderRoute() {
    // explore/trip 走下面的常驻容器，只有其它路由会进来。
    switch (route.name) {
      case 'trips':
        return <TripsPage tab={route.tab} />;
      case 'collab':
        return <CollabPage />;
      case 'profile':
        return <ProfilePage />;
      case 'account':
        return <AccountSettingsPage />;
      case 'forgot':
        return <ForgotPage />;
      case 'reset':
        return <ResetPage token={route.token} />;
      case 'verify':
        return <VerifyPage token={route.token} />;
      case 'terms':
        return <TermsPage />;
      case 'privacy':
        return <PrivacyPage />;
      case 'share':
        return <SharedTripPage token={route.token} onLogin={() => openAuth('login')} />;
      case 'invite':
        return (
          <section className={styles.invitePage}>
            <p className={styles.kicker}>协作邀请</p>
            <h1>有人想和你一起规划这趟旅行。</h1>
            {!user ? (
              <>
                <p>登录后即可加入，行程里的修改会实时同步给每位协作者。</p>
                <button type="button" className={styles.primary} onClick={() => openAuth('login')}>登录 / 注册</button>
              </>
            ) : invite.busy ? (
              <p role="status">正在接受邀请…</p>
            ) : invite.error ? (
              <>
                <p className={styles.error} role="alert">{invite.error}</p>
                <button type="button" className={styles.primary} onClick={() => acceptInvite(inviteToken)}>
                  重试
                </button>
              </>
            ) : (
              <p role="status">邀请已接受，正在打开行程…</p>
            )}
            <button type="button" className={styles.secondary} onClick={() => navigate('/explore')}>先去探索</button>
          </section>
        );
      default:
        return (
          <section className={styles.notFound}>
            <p className={styles.kicker}>404</p>
            <h1>这条路线不存在。</h1>
            <p>链接可能已经失效，或者地址写错了。</p>
            <button type="button" className={styles.primary} onClick={() => navigate('/explore')}>回到探索</button>
          </section>
        );
    }
  }

  if (loading) {
    return <div className={styles.loading} role="status">行迹<span aria-hidden="true">·</span>正在准备旅程</div>;
  }

  return (
    <div className={`${styles.shell} ${navClass}`}>
      {showNav && <TopNav active={tabFor(route.name)} user={user} onNavigate={navigate} onLogin={() => openAuth('login')} />}
      {(!online || restored) && (
        <div className={`${styles.connectivity} ${online ? styles.online : styles.offline}`} role="status">
          {online ? '网络已恢复' : '当前离线，修改会先保存在本机'}
        </div>
      )}
      <main className={styles.main} ref={mainRef} tabIndex={-1}>
        {/* 探索页常驻：生成中切 tab 不卸载 SSE，回来时进度和预览还在。 */}
        {exploreMounted ? (
          <div className={styles.keepAlive} hidden={!activeExplore}>
            <PageActiveProvider active={activeExplore}>
              <ErrorBoundary>
                <ExplorePage />
              </ErrorBoundary>
            </PageActiveProvider>
          </div>
        ) : null}
        {/* 当前行程页常驻：问 AI 时切去列表/我的，回复仍继续。 */}
        {tripHostId !== null ? (
          <div className={styles.keepAlive} hidden={activeTripId !== tripHostId}>
            <PageActiveProvider active={activeTripId === tripHostId}>
              <ErrorBoundary key={`trip-host-${tripHostId}`}>
                <TripWorkspacePage key={tripHostId} tripId={tripHostId} />
              </ErrorBoundary>
            </PageActiveProvider>
          </div>
        ) : null}
        {route.name !== 'explore' && route.name !== 'trip' ? (
          /* 页面级错误边界：单个页面崩溃时保留导航和会话，换路由即重置。 */
          <ErrorBoundary key={routeKey}>
            <Suspense fallback={<p className={styles.routeLoading} role="status">正在打开…</p>}>
              {renderRoute()}
            </Suspense>
          </ErrorBoundary>
        ) : null}
      </main>
      {showNav && <BottomNav active={tabFor(route.name)} onNavigate={navigate} />}
      <AuthDialog
        open={auth.open}
        initialMode={auth.mode}
        onClose={() => setAuth(current => ({ ...current, open: false, notice: undefined }))}
        onSuccess={handleAuthSuccess}
      />
      {auth.notice ? <p className={styles.srOnly} role="status">{auth.notice}</p> : null}
    </div>
  );
}