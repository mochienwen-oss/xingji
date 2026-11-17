import { useMemo, useState } from 'react';
import { useDraft } from '../app/providers/DraftProvider';
import { useSession } from '../app/providers/SessionProvider';
import { useTripList } from '../app/providers/TripListProvider';
import { useConfirm, useToast } from '../app/providers/ToastProvider';
import { useHashRoute } from '../app/routing/useHashRoute';
import { acceptTerms, message } from '../lib/api';
import { APP_VERSION } from '../lib/appInfo';
import { openAuth } from '../lib/auth-events';
import { useSupportEmail } from '../components/Feedback';
import { readMotionPref, saveMotionPref, type MotionPref } from '../lib/motion';
import { ArrowRightIcon, LogoutIcon, MailIcon, SettingsIcon } from '../components/icons';
import { TripCover } from '../components/trip/TripCover';
import { Avatar } from '../components/ui/Avatar';
import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Kicker } from '../components/ui/Kicker';
import { Skeleton } from '../components/ui/Skeleton';
import styles from './ProfilePage.module.css';
import type { TripSummary } from '../types/trip';

const RECENT_LIMIT = 3;

function tripTitle(trip: TripSummary): string {
  return trip.title?.trim() || trip.city + '旅行计划';
}

function useStats(trips: TripSummary[], savedPlaces: number) {
  return useMemo(() => {
    const cities = new Set<string>();
    for (const trip of trips) {
      const city = trip.city?.trim();
      if (city) cities.add(city);
    }
    return { trips: trips.length, cities: cities.size, places: savedPlaces };
  }, [trips, savedPlaces]);
}

/** 我的：账户身份、旅行统计、最近三段旅程、偏好与关于。 */
export function ProfilePage() {
  const { user, loading, logout, refresh } = useSession();
  const { trips, loading: tripsLoading, error: tripsError, refresh: refreshTrips } = useTripList();
  const { places } = useDraft();
  const { navigate } = useHashRoute();
  const confirm = useConfirm();
  const { toast } = useToast();
  const supportEmail = useSupportEmail();
  const [motion, setMotion] = useState<MotionPref>(readMotionPref);
  const [accepting, setAccepting] = useState(false);
  const [termsError, setTermsError] = useState('');
  const stats = useStats(trips, places.length);
  const recent = trips.slice(0, RECENT_LIMIT);

  function toggleMotion() {
    const next: MotionPref = motion === 'reduce' ? 'system' : 'reduce';
    setMotion(next);
    saveMotionPref(next);
  }

  async function handleLogout() {
    const ok = await confirm({
      title: '退出登录？',
      body: '行程仍保存在账号里，下次登录可以继续。',
      confirmLabel: '退出登录',
    });
    if (!ok) return;
    await logout();
    navigate('/explore', { replace: true });
  }

  async function handleAcceptTerms() {
    setAccepting(true);
    setTermsError('');
    try {
      await acceptTerms();
      await refresh();
      toast('已同意最新服务条款', 'success');
    } catch (error) {
      setTermsError(message(error));
    } finally {
      setAccepting(false);
    }
  }

  if (loading) {
    return (
      <main className={styles.page}>
        <div className={styles.shell} role="status" aria-live="polite">
          <Skeleton className={styles.skeletonKicker} />
          <Skeleton className={styles.skeletonTitle} />
          <Skeleton className={styles.skeletonBlock} />
          <p className={styles.loadingText}>正在加载你的旅行档案…</p>
        </div>
      </main>
    );
  }

  const verifiedLabel = user?.email
    ? user.emailVerified
      ? '已验证'
      : '待验证'
    : '未绑定';

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topline}>
          <Kicker className={styles.kicker}>行迹 · PROFILE</Kicker>
          {user ? (
            <button
              type="button"
              className={styles.settingsLink}
              onClick={() => navigate('/settings/account')}
            >
              <SettingsIcon size={16} />
              设置
              <ArrowRightIcon size={16} />
            </button>
          ) : (
            <span className={styles.guestTag}>游客模式</span>
          )}
        </div>

        <header className={styles.header}>
          <div className={styles.identity}>
            <Avatar name={user ? user.username : '游客'} size="lg" />
            <div className={styles.identityText}>
              <h1 className={styles.name}>{user ? user.username : '游客'}</h1>
              {user ? (
                <p className={styles.emailLine}>
                  <MailIcon size={16} />
                  <span className={styles.emailText}>{user.email || '未绑定邮箱'}</span>
                  <span
                    className={styles.badge}
                    data-state={user.email ? (user.emailVerified ? 'verified' : 'pending') : 'missing'}
                  >
                    {verifiedLabel}
                  </span>
                </p>
              ) : (
                <p className={styles.emailLine}>
                  登录后，旅程、收藏与设置会跟着账号走。
                </p>
              )}
            </div>
          </div>
        </header>

        {user?.needsTerms ? (
          <section className={styles.notice} aria-labelledby="terms-notice-title">
            <div>
              <h2 id="terms-notice-title" className={styles.noticeTitle}>
                服务条款已更新
              </h2>
              <p>继续使用前，请查看并同意最新条款；这不影响你浏览和规划行程。</p>
              <button type="button" className={styles.inlineLink} onClick={() => navigate('/terms?from=profile')}>
                查看条款
              </button>
            </div>
            <Button variant="secondary" onClick={() => void handleAcceptTerms()} loading={accepting}>
              同意
            </Button>
            {termsError ? (
              <p className={styles.noticeError} role="alert">
                {termsError}
              </p>
            ) : null}
          </section>
        ) : null}

        {user?.needsEmail ? (
          <section className={styles.notice} aria-labelledby="email-notice-title">
            <div>
              <h2 id="email-notice-title" className={styles.noticeTitle}>
                绑定邮箱，找回密码更方便
              </h2>
              <p>绑定后可用邮箱找回密码；不绑定也能继续使用行迹。邮箱不会出现在公开分享里。</p>
            </div>
            <Button variant="secondary" onClick={() => navigate('/settings/account')}>
              去绑定邮箱
            </Button>
          </section>
        ) : null}

        {user && user.email && !user.emailVerified ? (
          <section className={styles.notice} aria-labelledby="verify-notice-title">
            <div>
              <h2 id="verify-notice-title" className={styles.noticeTitle}>
                邮箱还没有验证
              </h2>
              <p>验证后可以更稳妥地找回密码；验证邮件有时会落在垃圾邮件里。</p>
            </div>
            <Button variant="secondary" onClick={() => navigate('/settings/account')}>
              去账户设置
            </Button>
          </section>
        ) : null}

        {user ? (
          <>
            {tripsLoading && trips.length === 0 ? (
              <div className={styles.statsSkeleton} role="status" aria-live="polite">
                <Skeleton className={styles.skeletonStat} />
                <Skeleton className={styles.skeletonStat} />
                <Skeleton className={styles.skeletonStat} />
                <span className={styles.srOnly}>正在统计旅程…</span>
              </div>
            ) : tripsError ? (
              <ErrorState
                title="旅程暂时没有取到"
                body={tripsError}
                onRetry={() => void refreshTrips()}
                retryLabel="重新加载"
              />
            ) : (
              <div className={styles.stats} role="list" aria-label="旅行概况">
                <div className={styles.stat} role="listitem">
                  <strong className={styles.statValue}>{stats.trips}</strong>
                  <span className={styles.statLabel}>段旅程</span>
                </div>
                <div className={styles.stat} role="listitem">
                  <strong className={styles.statValue}>{stats.cities}</strong>
                  <span className={styles.statLabel}>座城市</span>
                </div>
                <div className={styles.stat} role="listitem">
                  <strong className={styles.statValue}>{stats.places}</strong>
                  <span className={styles.statLabel}>个收藏地点</span>
                </div>
              </div>
            )}

            {tripsLoading && trips.length === 0 ? (
              <section className={styles.section} aria-label="正在加载最近旅程">
                <div className={styles.sectionHead}>
                  <h2>最近旅程</h2>
                </div>
                <div className={styles.recentSkeletonRow} aria-hidden="true">
                  <Skeleton className={styles.skeletonCard} />
                  <Skeleton className={styles.skeletonCard} />
                </div>
              </section>
            ) : tripsError ? null : recent.length === 0 ? (
              <EmptyState
                kicker="还没有旅程"
                title="从一次想去的地方开始"
                body="去探索页说一句想去哪、玩几天，第一段公路就从那里出发。"
                action={<Button onClick={() => navigate('/explore')}>去探索</Button>}
              />
            ) : (
              <section className={styles.section} aria-labelledby="recent-title">
                <div className={styles.sectionHead}>
                  <h2 id="recent-title">最近旅程</h2>
                  <button type="button" className={styles.inlineLink} onClick={() => navigate('/trips')}>
                    全部旅程
                  </button>
                </div>
                <ul className={styles.recentList}>
                  {recent.map(trip => (
                    <li key={trip.id} className={styles.recentItem}>
                      <button
                        type="button"
                        className={styles.recentCard}
                        aria-label={'打开' + tripTitle(trip)}
                        onClick={() => navigate('/trips/' + trip.id)}
                      >
                        <TripCover
                          city={trip.city}
                          days={trip.request?.days}
                          kicker="行迹 · TRIP"
                          className={styles.cover}
                        />
                        <span className={styles.recentCaption}>
                          <span className={styles.recentTitle}>{tripTitle(trip)}</span>
                          <span className={styles.recentMeta}>
                            {trip.city}
                            {trip.request?.days ? ' · ' + trip.request.days + ' 天' : ''}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        ) : (
          <>
            <section className={styles.guestCard} aria-labelledby="guest-title">
              <Kicker className={styles.kicker}>从这里开始</Kicker>
              <h2 id="guest-title" className={styles.guestTitle}>
                把旅程留在账号里
              </h2>
              <p className={styles.guestBody}>
                保存行程、跨设备继续，也能把路线分享给同行的人。现在登录，下一次打开就不用重来。
              </p>
              <div className={styles.guestActions}>
                <Button onClick={() => openAuth('login')}>登录 / 注册</Button>
                <Button variant="secondary" onClick={() => openAuth('register')}>
                  注册新账号
                </Button>
              </div>
            </section>

            <section className={styles.section} aria-labelledby="sample-title">
              <div className={styles.sectionHead}>
                <h2 id="sample-title">旅程示例</h2>
                <span className={styles.sampleTag}>示例</span>
              </div>
              <figure className={styles.sample}>
                <TripCover city="杭州" days={3} kicker="行迹 · 示例" />
                <figcaption className={styles.sampleCaption}>
                  示例 · 杭州三日。登录后，这里会换成你最近保存的旅程。
                </figcaption>
              </figure>
            </section>
          </>
        )}

        <section className={styles.section} aria-labelledby="settings-title">
          <div className={styles.sectionHead}>
            <h2 id="settings-title">账户与偏好</h2>
          </div>
          <div className={styles.rows}>
            {user ? (
              <button
                type="button"
                className={styles.row}
                onClick={() => navigate('/settings/account')}
              >
                <span className={styles.rowText}>
                  <span className={styles.rowTitle}>账户设置</span>
                  <span className={styles.rowHint}>邮箱、密码、条款与注销</span>
                </span>
                <ArrowRightIcon size={18} className={styles.rowArrow} />
              </button>
            ) : null}

            <button
              type="button"
              className={styles.row}
              role="switch"
              aria-checked={motion === 'reduce'}
              onClick={toggleMotion}
            >
              <span className={styles.rowText}>
                <span className={styles.rowTitle}>减少界面动效</span>
                <span className={styles.rowHint}>关闭抽屉与卡片的过渡动画，适合晕动敏感时使用。</span>
              </span>
              <span className={styles.switchTrack} data-on={motion === 'reduce'} aria-hidden="true">
                <span className={styles.switchThumb} />
              </span>
            </button>

            <button type="button" className={styles.row} onClick={() => navigate('/terms?from=profile')}>
              <span className={styles.rowText}>
                <span className={styles.rowTitle}>服务条款</span>
                <span className={styles.rowHint}>查看行迹 Trip 的服务说明</span>
              </span>
              <ArrowRightIcon size={18} className={styles.rowArrow} />
            </button>

            <button type="button" className={styles.row} onClick={() => navigate('/privacy?from=profile')}>
              <span className={styles.rowText}>
                <span className={styles.rowTitle}>隐私政策</span>
                <span className={styles.rowHint}>了解地点与 AI 规划数据如何被处理</span>
              </span>
              <ArrowRightIcon size={18} className={styles.rowArrow} />
            </button>
          </div>
        </section>

        {user ? (
          <div className={styles.logoutRow}>
            <Button variant="secondary" onClick={() => void handleLogout()}>
              <LogoutIcon size={18} />
              退出登录
            </Button>
          </div>
        ) : null}

        <section className={styles.section} aria-labelledby="about-title">
          <div className={styles.sectionHead}>
            <h2 id="about-title">关于行迹</h2>
          </div>
          <dl className={styles.about}>
            <div className={styles.aboutRow}>
              <dt>版本</dt>
              <dd>行迹 Trip {APP_VERSION}</dd>
            </div>
            <div className={styles.aboutRow}>
              <dt>地图与地点</dt>
              <dd>地点搜索与路线基础数据来自高德地图。</dd>
            </div>
            <div className={styles.aboutRow}>
              <dt>AI 规划</dt>
              <dd>行程由 DeepSeek 模型生成，仅供参考；出行前请核实开放时间、票价与交通。</dd>
            </div>
            {supportEmail ? (
              <div className={styles.aboutRow}>
                <dt>联系我们</dt>
                <dd>
                  反馈问题或建议，可以发邮件到 <a href={'mailto:' + supportEmail}>{supportEmail}</a>。
                </dd>
              </div>
            ) : null}
          </dl>
        </section>

        <p className={styles.foot}>行迹 Trip · 演示版 · 纸白、砖红与一条条真实的路</p>
      </div>
    </main>
  );
}
