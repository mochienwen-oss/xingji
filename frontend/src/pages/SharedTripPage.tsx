import { useEffect, useState } from "react";
import { BrandMark } from "../components/BrandMark";
import { MapView } from "../components/MapView";
import { SegmentedTabs, tabPanel } from "../components/SegmentedTabs";
import { BackIcon, RouteIcon, ShareIcon } from "../components/icons";
import { PlaceTrustBadge, PlaceTrustSummary } from "../components/trip/PlaceTrust";
import { TripHealth } from "../components/trip/TripHealth";
import { TripCover } from "../components/trip/TripCover";
import { AiNotice } from "../components/ui/AiNotice";
import { ReportDialog } from "../components/ReportDialog";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Skeleton } from "../components/ui/Skeleton";
import { Toast } from "../components/ui/Toast";
import { ApiError, api } from "../lib/api";
import { useSession } from "../app/providers/SessionProvider";
import { amapNavigationUrl, navigationMode } from "../lib/amapNavigation";
import { openAuth } from "../lib/auth-events";
import { markForkDatePrompt } from "../lib/forkPrompt";
import { scheduleDay } from "../lib/schedule";
import type { Day, Place, Stop } from "../types/trip";
import styles from "./SharedTripPage.module.css";

type Lang = "zh" | "en";
type Status = "loading" | "ready" | "ended" | "error";
type CopyProblem = "none" | "login" | "failed" | "unavailable";
type SharedTripResponse = {
  id?: number;
  title: string | null;
  city: string;
  request: {
    city: string;
    days: number;
    start_date: string | null;
    transport: string;
  };
  days: Day[];
  place_notice?: string;
  /** 分享者用户名；后端 view_share 只下发 owner。 */
  owner?: string | null;
};

type Copy = {
  pageTitle: string;
  opening: string;
  backToExplore: string;
  backToTrips: string;
  brandHome: string;
  language: string;
  chinese: string;
  english: string;
  readonlyShare: string;
  sharedBy: (name: string) => string;
  days: (count: number) => string;
  factDays: string;
  factStops: string;
  factDistance: string;
  distance: (meters: number) => string;
  dateTbd: string;
  transportTbd: string;
  transport: Record<string, string>;
  overview: string;
  day: (index: number) => string;
  itinerary: string;
  map: string;
  mapCredit: string;
  coverKicker: string;
  tripFallback: (city: string) => string;
  placeTbd: string;
  addressTbd: string;
  fixedStart: string;
  estimated: string;
  timeTbd: string;
  late: string;
  suggestedStay: (minutes: number) => string;
  showOnMap: string;
  navigate: string;
  noTime: string;
  noStops: string;
  noDays: string;
  aiNotice: string;
  disclaimer: string;
  footnote: string;
  reportTrip: string;
  copyTrip: string;
  copyToTrips: string;
  copying: string;
  copyUnavailable: string;
  loginToCopy: string;
  signIn: string;
  copyFailed: string;
  manualCopy: string;
  copyLink: string;
  linkCopied: string;
  linkCopyFailed: string;
  shareLink: string;
  copiedToast: string;
  planOwn: string;
  routeTime: (seconds: number | null) => string;
  endedKicker: string;
  endedTitle: string;
  endedBody: string;
  exploreTrip: string;
  loadErrorTitle: string;
  loadErrorBody: string;
  retry: string;
  nextDay: string;
  plusDay: (days: number) => string;
};

/** 页面所有 chrome 文案集中在这里；城市、景点等数据专名保持原样。 */
const COPY = {
  zh: {
    pageTitle: "分享的行程",
    opening: "正在打开分享…",
    backToExplore: "返回发现",
    backToTrips: "返回我的行程",
    brandHome: "行迹首页",
    language: "界面语言",
    chinese: "中文",
    english: "English",
    readonlyShare: "只读分享",
    sharedBy: (name: string) => `由 @${name} 分享`,
    days: (count: number) => `${count} 天`,
    factDays: "天数",
    factStops: "地点",
    factDistance: "总里程",
    distance: (meters: number) => (meters < 1000
      ? `${Math.round(meters)} 米`
      : `${meters < 10000 ? (meters / 1000).toFixed(1) : Math.round(meters / 1000)} 公里`),
    dateTbd: "日期待定",
    transportTbd: "交通待定",
    transport: { walking: "步行", driving: "驾车", transit: "公交" },
    overview: "总览",
    day: (index: number) => `第 ${index} 天`,
    itinerary: "行程日期",
    map: "地图与路线",
    mapCredit: "地图与路线由高德提供",
    coverKicker: "行迹 · TRIP",
    tripFallback: (city: string) => `${city}旅行计划`,
    placeTbd: "未命名地点",
    addressTbd: "地址暂无信息",
    fixedStart: "固定开始",
    estimated: "预计",
    timeTbd: "时间待定",
    late: " · 晚于固定时间",
    suggestedStay: (minutes: number) => `建议停留 ${minutes} 分钟`,
    showOnMap: "在地图上查看",
    navigate: "高德导航",
    noTime: "时间暂无信息",
    noStops: "这一天还没有安排地点。",
    noDays: "这份行程还没有安排日程。",
    aiNotice: "行程由 AI 生成，地点、开放时间与交通请在出发前核实。",
    disclaimer: "开放时间、票价和交通可能变化，请在出发前向官方核实。",
    footnote: "此页面仅供查看，内容可能随行程更新。",
    reportTrip: "举报这份行程",
    copyTrip: "复制此行程",
    copyToTrips: "复制此行程到我的行程",
    copying: "正在复制…",
    copyUnavailable: "这份行程暂时无法复制。",
    loginToCopy: "登录后即可把这份行程复制到我的行程。也可以先复制分享链接。",
    signIn: "登录 / 注册",
    copyFailed: "复制没有成功，请复制下面的分享链接。",
    manualCopy: "也可复制分享链接",
    copyLink: "复制分享链接",
    linkCopied: "分享链接已复制。",
    linkCopyFailed: "复制失败，请在上面手动选择链接。",
    shareLink: "分享链接",
    copiedToast: "已复制到我的行程。",
    planOwn: "打开行迹，规划我的路线",
    routeTime: (seconds: number | null) => (seconds == null ? "时间暂无信息" : `约 ${Math.max(1, Math.ceil(seconds / 60))} 分钟`),
    endedKicker: "分享已结束",
    endedTitle: "这条分享已结束",
    endedBody: "链接可能已被撤销，或这份行程已不再公开。",
    exploreTrip: "去行迹看看",
    loadErrorTitle: "暂时打不开这份分享",
    loadErrorBody: "请检查网络后重试；链接本身可能仍然有效。",
    retry: "重试",
    nextDay: "次日",
    plusDay: (days: number) => `+${days} 天`,
  },
  en: {
    pageTitle: "A shared trip",
    opening: "Opening shared trip…",
    backToExplore: "Back to Explore",
    backToTrips: "Back to my trips",
    brandHome: "Xingji home",
    language: "Interface language",
    chinese: "Chinese",
    english: "English",
    readonlyShare: "Read-only",
    sharedBy: (name: string) => `Shared by @${name}`,
    days: (count: number) => (count === 1 ? "1 day" : `${count} days`),
    factDays: "Days",
    factStops: "Stops",
    factDistance: "Distance",
    distance: (meters: number) => (meters < 1000
      ? `${Math.round(meters)} m`
      : `${meters < 10000 ? (meters / 1000).toFixed(1) : Math.round(meters / 1000)} km`),
    dateTbd: "Date TBD",
    transportTbd: "Transport TBD",
    transport: { walking: "Walk", driving: "Drive", transit: "Transit" },
    overview: "Overview",
    day: (index: number) => `Day ${index}`,
    itinerary: "Itinerary days",
    map: "Map & route",
    mapCredit: "Map data and routes by Amap",
    coverKicker: "行迹 · TRIP",
    tripFallback: (city: string) => `Trip to ${city}`,
    placeTbd: "Unnamed stop",
    addressTbd: "Address not available",
    fixedStart: "Fixed start",
    estimated: "Est.",
    timeTbd: "Time TBD",
    late: " · later than fixed time",
    suggestedStay: (minutes: number) => `Suggested stay: ${minutes} min`,
    showOnMap: "Show on map",
    navigate: "Navigate in Amap",
    noTime: "No time info",
    noStops: "No stops planned for this day.",
    noDays: "This trip has no days yet.",
    aiNotice: "Itinerary generated by AI. Please verify places, hours and transit before you go.",
    disclaimer: "Hours, tickets and transit may change. Please verify before departure.",
    footnote: "This page is read-only; content may update as the trip changes.",
    reportTrip: "Report this trip",
    copyTrip: "Copy this trip",
    copyToTrips: "Copy to my trips",
    copying: "Copying…",
    copyUnavailable: "This trip cannot be copied right now.",
    loginToCopy: "Sign in to copy this trip to your trips. You can also copy the share link below.",
    signIn: "Sign in / Register",
    copyFailed: "The trip could not be copied. Copy the share link below instead.",
    manualCopy: "Or copy the share link",
    copyLink: "Copy share link",
    linkCopied: "Share link copied.",
    linkCopyFailed: "Copy failed — select the link above manually.",
    shareLink: "Share link",
    copiedToast: "Copied to your trips.",
    planOwn: "Plan my own route",
    routeTime: (seconds: number | null) => (seconds == null ? "No time info" : `~${Math.max(1, Math.ceil(seconds / 60))} min`),
    endedKicker: "SHARE ENDED",
    endedTitle: "This share has ended",
    endedBody: "The link may have been revoked, or the trip is no longer public.",
    exploreTrip: "Explore Trip",
    loadErrorTitle: "Could not open this share",
    loadErrorBody: "Check your connection and try again. The link itself may still be fine.",
    retry: "Try again",
    nextDay: "Next day",
    plusDay: (days: number) => `+${days} days`,
  },
} satisfies Record<Lang, Copy>;

const EMPTY_BACKLOG: Stop[] = [];

function cleanOwner(value: string | null | undefined): string | null {
  const name = value?.trim().replace(/^@+/, "");
  return name || null;
}

/** 老行程里交通方式可能存的是中文，统一映射到 copy.transport 的键。 */
const TRANSPORT_ALIAS: Record<string, string> = {
  "步行": "walking",
  "驾车": "driving",
  "开车": "driving",
  "公交": "transit",
  "公共交通": "transit",
  "地铁": "transit",
};

function transportKey(value: string | null | undefined): string {
  const raw = value?.trim() ?? "";
  return TRANSPORT_ALIAS[raw] ?? raw;
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!year || month < 1 || month > 12 || day < 1 || day > 31) return null;
  return new Date(Date.UTC(year, month - 1, day));
}

function formatDate(date: Date, lang: Lang, long: boolean): string {
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    ...(long ? { year: "numeric" as const } : {}),
    month: lang === "zh" ? "long" : "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

function formatLongDate(value: string | null | undefined, lang: Lang): string {
  const date = parseDate(value);
  return date ? formatDate(date, lang, true) : "";
}

function formatDayDate(start: string | null | undefined, dayIndex: number, lang: Lang): string {
  const date = parseDate(start);
  if (!date) return "";
  return formatDate(new Date(date.getTime() + dayIndex * 86400000), lang, false);
}

function formatCoverRange(start: string | null | undefined, dayCount: number, lang: Lang): string | undefined {
  const date = parseDate(start);
  if (!date) return undefined;
  const first = formatDate(date, lang, true);
  if (dayCount <= 1) return first;
  const last = formatDate(new Date(date.getTime() + (dayCount - 1) * 86400000), lang, true);
  return `${first} – ${last}`;
}

function clockMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^(\d{1,2}):(\d{2})/.exec(value);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

function formatClock(value: number, copy: Copy): string {
  const dayOffset = Math.floor(value / 1440);
  const minute = ((value % 1440) + 1440) % 1440;
  const clock = `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  if (dayOffset <= 0) return clock;
  return `${dayOffset === 1 ? copy.nextDay : copy.plusDay(dayOffset)} ${clock}`;
}

type DayBlockProps = {
  day: Day;
  dayIndex: number;
  startDate: string | null;
  mode: string;
  copy: Copy;
  lang: Lang;
  onFocusPlace: (place: Place) => void;
};

function DayBlock({ day, dayIndex, startDate, mode, copy, lang, onFocusPlace }: DayBlockProps) {
  const schedule = scheduleDay(day, mode);
  const dateLabel = formatDayDate(startDate, dayIndex, lang);
  return (
    <section className={styles.dayBlock} aria-labelledby={`shared-day-${dayIndex}`}>
      <header className={styles.dayHead}>
        <h2 id={`shared-day-${dayIndex}`} className={styles.dayTitle}>{copy.day(dayIndex + 1)}</h2>
        {dateLabel ? <span className={styles.dayDate}>{dateLabel}</span> : null}
      </header>
      {day.stops.length === 0 ? (
        <p className={styles.emptyDay}>{copy.noStops}</p>
      ) : (
        <ol className={styles.stops}>
          {day.stops.map((stop, stopIndex) => {
            const timing = schedule.stops[stopIndex];
            const fixedMinutes = clockMinutes(stop.fixed_time);
            const fixedLabel = fixedMinutes == null
              ? null
              : formatClock(fixedMinutes + (stop.fixed_next_day ? 1440 : 0), copy);
            const activity = stop.activity?.trim() ?? "";
            const placeName = stop.place.name?.trim() ?? "";
            const title = activity || placeName || copy.placeTbd;
            const placeParts: string[] = [];
            if (activity && activity !== placeName) placeParts.push(placeName);
            placeParts.push(stop.place.address?.trim() || copy.addressTbd);
            const route = day.routes[stopIndex];
            const hasNext = stopIndex < day.stops.length - 1;
            return (
              <li key={stop.place.id || stopIndex} className={styles.stopRow}>
                <span className={styles.stopNumber}>{dayIndex + 1}.{stopIndex + 1}</span>
                <div className={styles.stopBody}>
                  <h3 className={styles.stopTitle}>{title}</h3>
                  <p className={styles.address}>{placeParts.filter(Boolean).join(" · ")}</p>
                  <div className={styles.stopFacts}>
                    {fixedLabel ? (
                      <span className={styles.stopFact}>
                        <span className={styles.factLabel}>{copy.fixedStart}</span>
                        <time>{fixedLabel}</time>
                      </span>
                    ) : null}
                    <span className={styles.stopFact}>
                      <span className={styles.factLabel}>{copy.estimated}</span>
                      {timing && timing.start != null && timing.departure != null ? (
                        <>
                          <time>{formatClock(timing.start, copy)}</time>
                          <span aria-hidden="true">–</span>
                          <time>{formatClock(timing.departure, copy)}</time>
                          {timing.late ? <span className={styles.late}>{copy.late}</span> : null}
                        </>
                      ) : (
                        <span>{copy.timeTbd}</span>
                      )}
                    </span>
                    <span className={styles.stopFact}>{copy.suggestedStay(stop.duration)}</span>
                    <PlaceTrustBadge place={stop.place} lang={lang} />
                  </div>
                  <div className={styles.stopLinks}>
                    <button type="button" className={styles.mapLink} onClick={() => onFocusPlace(stop.place)}>
                      {copy.showOnMap}
                    </button>
                    {amapNavigationUrl(stop.place, navigationMode(mode)) ? (
                      <a
                        className={styles.mapLink}
                        href={amapNavigationUrl(stop.place, navigationMode(mode)) ?? undefined}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        {copy.navigate}
                      </a>
                    ) : null}
                  </div>
                  {hasNext ? (
                    <div className={styles.routeConnector}>
                      <RouteIcon size={14} />
                      <span>
                        {copy.transport[transportKey(route?.mode)] ?? copy.transportTbd}
                        <span aria-hidden="true"> · </span>
                        {copy.routeTime(route?.duration ?? null)}
                      </span>
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export function SharedTripPage({ token, onLogin }: { token: string; onLogin?: () => void }) {
  const [lang, setLang] = useState<Lang>("zh");
  const [status, setStatus] = useState<Status>("loading");
  const [trip, setTrip] = useState<SharedTripResponse | null>(null);
  // 分享页也在 SessionProvider 内，直接读全局会话：页内登录/退出会立即反映到 CTA，
  // 不再自己请求 /me（那只能反映挂载那一刻的状态）。
  const { user: sessionUser, loading: sessionLoading } = useSession();
  const [selectedId, setSelectedId] = useState("all");
  const [focusPlace, setFocusPlace] = useState<Place | null>(null);
  const [copyBusy, setCopyBusy] = useState(false);
  const [copyProblem, setCopyProblem] = useState<CopyProblem>("none");
  const [linkCopyFailed, setLinkCopyFailed] = useState(false);
  const [toast, setToast] = useState<{ id: number; kind: "fork" | "link" } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [reportOpen, setReportOpen] = useState(false);

  const copy: Copy = COPY[lang];

  useEffect(() => {
    let alive = true;
    setStatus("loading");
    setTrip(null);
    setCopyProblem("none");
    setSelectedId("all");
    setFocusPlace(null);
    api<SharedTripResponse>("/shares/view", { method: "POST", body: JSON.stringify({ token }) })
      .then((data) => {
        if (!alive) return;
        // 分享被撤销/删除时后端可能回 200 但空体：绝不能停在白屏。
        if (!data || typeof data !== "object" || !data.request) {
          setStatus("ended");
          return;
        }
        setTrip({ ...data, days: Array.isArray(data.days) ? data.days : [] });
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && (error.status === 404 || error.status === 410)) setStatus("ended");
        else setStatus("error");
      });
    return () => { alive = false; };
  }, [token, reloadKey]);

  useEffect(() => {
    const previous = document.documentElement.lang;
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    return () => { document.documentElement.lang = previous; };
  }, [lang]);

  const city = trip ? trip.request.city || trip.city || "" : "";
  const tripTitle = trip ? trip.title?.trim() || copy.tripFallback(city) : copy.pageTitle;

  useEffect(() => {
    const previous = document.title;
    document.title = `${tripTitle} · 行迹`;
    return () => { document.title = previous; };
  }, [tripTitle]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);


  const ownerName = trip ? cleanOwner(trip.owner) : null;
  const dayCount = trip ? trip.request.days || trip.days.length : 0;
  const stopCount = trip ? trip.days.reduce((total, day) => total + day.stops.length, 0) : 0;
  const totalMeters = trip ? trip.days.reduce((total, day) => total + (day.routes ?? []).reduce(
    (sum, route) => sum + (typeof route.distance === "number" && route.distance > 0 ? route.distance : 0), 0), 0) : 0;
  const startLabel = trip ? formatLongDate(trip.request.start_date, lang) || copy.dateTbd : "";
  const coverRange = trip ? formatCoverRange(trip.request.start_date, dayCount, lang) : undefined;
  const transportLabel = trip ? copy.transport[transportKey(trip.request.transport)] ?? copy.transportTbd : "";
  const tabs = trip
    ? [{ id: "all", label: copy.overview }, ...trip.days.map((_, index) => ({ id: String(index), label: copy.day(index + 1) }))]
    : [];
  const activeDayIndex = selectedId === "all" ? -1 : Number(selectedId);
  const activeDay = trip && Number.isInteger(activeDayIndex) && activeDayIndex >= 0 ? trip.days[activeDayIndex] : undefined;
  // 会话加载期间按游客渲染 CTA，避免登录用户先看到「复制行程」再闪烁成「打开我的行程」。
  const signedIn = !sessionLoading && Boolean(sessionUser);
  const backHref = signedIn ? "#/trips" : "#/explore";
  const backLabel = signedIn ? copy.backToTrips : copy.backToExplore;
  const shareUrl = typeof window !== "undefined" ? window.location.href : "";
  const problemText = copyProblem === "login"
    ? copy.loginToCopy
    : copyProblem === "failed"
      ? copy.copyFailed
      : copyProblem === "unavailable"
        ? copy.copyUnavailable
        : "";

  function requestLogin() {
    if (onLogin) onLogin();
    else openAuth("save");
  }

  async function copyTrip() {
    if (!trip || copyBusy) return;
    if (typeof trip.id !== "number") {
      setCopyProblem("unavailable");
      return;
    }
    setCopyBusy(true);
    setCopyProblem("none");
    try {
      const forked = await api<{ id?: number }>("/shares/fork", { method: "POST", body: JSON.stringify({ token }) });
      if (typeof forked?.id === "number") {
        // 复制是「拿走一份自己的行程」，直接打开并提示设置出发日期，
        // 比停在只读页更接近用户下一步要做的事。
        markForkDatePrompt(forked.id);
        window.location.hash = `#/trips/${forked.id}`;
        return;
      }
      setToast((current) => ({ id: (current?.id ?? 0) + 1, kind: "fork" }));
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) setCopyProblem("login");
      else if (error instanceof ApiError && error.status === 404) setCopyProblem("unavailable");
      else setCopyProblem("failed");
    } finally {
      setCopyBusy(false);
    }
  }

  /** 页面上的「复制分享链接」：报告里要求的剪贴板动作，fork 失败或未登录时也能用。 */
  async function copyShareLink() {
    const target = shareUrl || (typeof window !== "undefined" ? window.location.href : "");
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("clipboard unavailable");
      }
      await navigator.clipboard.writeText(target);
      setLinkCopyFailed(false);
      setToast((current) => ({ id: (current?.id ?? 0) + 1, kind: "link" }));
    } catch {
      setLinkCopyFailed(true);
      const input = typeof document !== "undefined" ? document.getElementById("shared-trip-link") : null;
      if (input instanceof HTMLInputElement) {
        input.focus();
        input.select();
      }
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <a className={styles.back} href={backHref} aria-label={backLabel}>
            <BackIcon />
          </a>
          <a className={styles.wordmark} href="#/explore" aria-label={copy.brandHome}>
            <BrandMark />
            <span className={styles.wordmarkText}>行迹</span>
          </a>
          <div className={styles.langGroup} role="group" aria-label={copy.language}>
            <button
              type="button"
              className={styles.langButton}
              aria-pressed={lang === "zh"}
              aria-label={copy.chinese}
              onClick={() => setLang("zh")}
            >
              中
            </button>
            <button
              type="button"
              className={styles.langButton}
              aria-pressed={lang === "en"}
              aria-label={copy.english}
              onClick={() => setLang("en")}
            >
              EN
            </button>
          </div>
        </div>
      </header>

      <div className={styles.main}>
        {status === "loading" ? (
          <section className={styles.loading} aria-label={copy.opening}>
            <Skeleton className={styles.skeletonCover} />
            <Skeleton className={styles.skeletonTitle} />
            <Skeleton className={styles.skeletonLine} />
            <Skeleton className={styles.skeletonLineShort} />
            <p className={styles.loadingText} role="status">{copy.opening}</p>
          </section>
        ) : null}

        {status === "ended" ? (
          <EmptyState
            className={styles.stateColumn}
            kicker={copy.endedKicker}
            title={copy.endedTitle}
            body={copy.endedBody}
            action={<a className={styles.primaryLink} href="#/explore">{copy.exploreTrip}</a>}
          />
        ) : null}

        {status === "error" ? (
          <ErrorState
            className={styles.stateColumn}
            title={copy.loadErrorTitle}
            body={copy.loadErrorBody}
            onRetry={() => setReloadKey((value) => value + 1)}
            retryLabel={copy.retry}
          />
        ) : null}

        {status === "ready" && trip ? (
          <>
            <section className={styles.intro} aria-labelledby="shared-trip-title">
              <div className={styles.shareLine}>
                {ownerName ? (
                  <>
                    <ShareIcon size={16} />
                    <span>{copy.sharedBy(ownerName)}</span>
                  </>
                ) : null}
                <span className={styles.readonlyChip}>{copy.readonlyShare}</span>
              </div>
              <div className={styles.coverFrame}>
                <TripCover
                  city={city}
                  dateRange={coverRange}
                  kicker={copy.coverKicker}
                  size="hero"
                  className={styles.coverFill}
                />
              </div>
              <h1 id="shared-trip-title" className={styles.title}>{tripTitle}</h1>
              <dl className={styles.facts}>
                <div className={styles.fact}>
                  <dt>{copy.factDays}</dt>
                  <dd>{dayCount}</dd>
                </div>
                <div className={styles.fact}>
                  <dt>{copy.factStops}</dt>
                  <dd>{stopCount}</dd>
                </div>
                <div className={styles.fact}>
                  <dt>{copy.factDistance}</dt>
                  <dd>{totalMeters > 0 ? copy.distance(totalMeters) : "—"}</dd>
                </div>
              </dl>
              <p className={styles.meta}>
                <span>{copy.days(dayCount)}</span>
                <span className={styles.metaDot} aria-hidden="true">·</span>
                <span>{startLabel}</span>
                <span className={styles.metaDot} aria-hidden="true">·</span>
                <span>{transportLabel}</span>
              </p>
              <PlaceTrustSummary
                places={trip.days.flatMap(day => day.stops.map(stop => stop.place))}
                lang={lang}
              />
              <TripHealth days={trip.days} request={trip.request} lang={lang} />
            </section>

            <section className={styles.mapSection} aria-labelledby="shared-map-title">
              <h2 id="shared-map-title" className={styles.sectionKicker}>{copy.map}</h2>
              <div className={styles.mapFrame}>
                <MapView
                  days={trip.days}
                  city={city}
                  backlog={EMPTY_BACKLOG}
                  showBacklog={false}
                  focusPlace={focusPlace}
                  tripId={trip.id}
                  lang={lang}
                  showCaption={false}
                />
              </div>
              <p className={styles.mapCredit}>{copy.mapCredit}</p>
            </section>

            <section className={styles.itinerary} aria-label={copy.itinerary}>
              <SegmentedTabs
                tabs={tabs}
                value={selectedId}
                onChange={(id) => { setSelectedId(id); setFocusPlace(null); }}
                ariaLabel={copy.itinerary}
                idPrefix="shared"
                className={styles.tabs}
              />
              <div {...tabPanel("shared", selectedId)} className={styles.tabPanel}>
                {activeDay ? (
                  <DayBlock
                    day={activeDay}
                    dayIndex={activeDayIndex}
                    startDate={trip.request.start_date}
                    mode={trip.request.transport}
                    copy={copy}
                    lang={lang}
                    onFocusPlace={setFocusPlace}
                  />
                ) : trip.days.length > 0 ? (
                  trip.days.map((day, index) => (
                    <DayBlock
                      key={index}
                      day={day}
                      dayIndex={index}
                      startDate={trip.request.start_date}
                      mode={trip.request.transport}
                      copy={copy}
                      lang={lang}
                      onFocusPlace={setFocusPlace}
                    />
                  ))
                ) : (
                  <p className={styles.emptyDay}>{copy.noDays}</p>
                )}
              </div>
              <AiNotice className={styles.aiNotice}>{copy.aiNotice}</AiNotice>
              <p className={styles.disclaimer}>{copy.disclaimer}</p>
              <p className={styles.footnote}>{copy.footnote}</p>
              <button type="button" className={styles.reportLink} onClick={() => setReportOpen(true)}>
                {copy.reportTrip}
              </button>
            </section>
          </>
        ) : null}
      </div>

      {status === "ready" && trip ? (
        <>
          <ReportDialog
            open={reportOpen}
            target={{ kind: "share", token }}
            onClose={() => setReportOpen(false)}
            lang={lang}
          />
          {toast ? (
            <div className={styles.toastHost} role="status" aria-live="polite" aria-atomic="true">
              <Toast
                id={toast.id}
                message={toast.kind === "link" ? copy.linkCopied : copy.copiedToast}
                tone="success"
              />
            </div>
          ) : null}
          <div className={styles.ctaDock}>
            <div className={styles.ctaInner}>
              {copyProblem !== "none" ? (
                <div className={styles.copyProblem} role="alert">
                  <p className={styles.copyProblemText}>{problemText}</p>
                  <label className={styles.shareLabel} htmlFor="shared-trip-link">{copy.shareLink}</label>
                  <input
                    id="shared-trip-link"
                    className={styles.shareInput}
                    readOnly
                    value={shareUrl}
                    onFocus={(event) => event.currentTarget.select()}
                  />
                  {copyProblem === "login" ? (
                    <Button type="button" variant="secondary" className={styles.signInButton} onClick={requestLogin}>
                      {copy.signIn}
                    </Button>
                  ) : null}
                  <Button type="button" variant="secondary" className={styles.linkCopyButton} onClick={copyShareLink}>
                    {copy.copyLink}
                  </Button>
                  {linkCopyFailed ? (
                    <p className={styles.copyProblemText} role="status">{copy.linkCopyFailed}</p>
                  ) : null}
                </div>
              ) : null}
              <div className={signedIn ? styles.ctaRowSingle : styles.ctaRow}>
                {signedIn ? (
                  <Button
                    type="button"
                    variant="primary"
                    size="lg"
                    className={styles.ctaButton}
                    loading={copyBusy}
                    onClick={copyTrip}
                  >
                    {copyBusy ? copy.copying : copy.copyToTrips}
                  </Button>
                ) : (
                  <>
                    <a className={styles.ctaPrimary} href="#/explore">{copy.planOwn}</a>
                    <Button
                      type="button"
                      variant="secondary"
                      size="lg"
                      className={styles.ctaButton}
                      loading={copyBusy}
                      onClick={copyTrip}
                    >
                      {copyBusy ? copy.copying : copy.copyTrip}
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
