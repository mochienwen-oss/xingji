import { useEffect, useRef, useState } from "react";
import { message } from "../lib/api";
import { loadAmap } from "../lib/mapLoader";
import { routeStrokeColor } from "../lib/token-color";
import { needsCheck } from "../lib/verification";
import type { Day, Place, Route, Stop } from "../types/trip";

declare global {
  interface Window {
    AMap: any;
    _AMapSecurityConfig: { securityJsCode: string };
  }
}

/** 经纬度字符串先做正则校验再拆分，空值/半截数据直接跳过。 */
const LOCATION_PATTERN = /^\s*-?\d{1,3}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?\s*$/;
function parseLocation(value: string | null | undefined): [number, number] | null {
  if (!value || !LOCATION_PATTERN.test(value)) return null;
  const [lng, lat] = value.split(",").map(Number);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return null;
  return [lng, lat];
}

/** 一段路线要画的线：path 为折线坐标，dashed 表示路线数据暂缺、按直线示意。 */
export type RouteLine = { path: number[][]; dashed: boolean };
type LineRecord = { overlay: any; pathKey: string };

/** 该段有没有可画的真实折线：不足两点的路径高德也画不出来。 */
function hasPolyline(route: Route | undefined) {
  return Boolean(route && Array.isArray(route.polyline)
    && route.polyline.some((path) => Array.isArray(path) && path.length >= 2));
}

/**
 * 覆盖物构建前的纯计算：真实折线按段展开成实线；相邻站点之间没有路线对象、
 * 或折线里没有一条能画的路径时，补一条虚线直线兜底。虚线只代表「路线数据暂缺，
 * 按直线示意」，有真实折线的段绝不叠虚线。
 */
export function buildRouteLines(days: Day[]): Map<string, RouteLine> {
  const lines = new Map<string, RouteLine>();
  days.forEach((day, dayIndex) => {
    day.routes.forEach((route, index) => {
      (Array.isArray(route.polyline) ? route.polyline : []).forEach((path, pathIndex) => {
        if (!Array.isArray(path) || path.length < 2) return;
        lines.set(`day-${dayIndex}-${index}-${pathIndex}-${route.origin}-${route.destination}-${route.mode}`, { path, dashed: false });
      });
    });
    day.stops.forEach((stop, index) => {
      const next = day.stops[index + 1];
      if (!next || hasPolyline(day.routes[index])) return;
      const from = parseLocation(stop.place.location);
      const to = parseLocation(next.place.location);
      if (!from || !to) return;
      // 虚线 key 只按天和段序号，不依赖 route.origin/destination：缺 route 的段拿不到它们。
      lines.set(`day-${dayIndex}-gap-${index}`, { path: [from, to], dashed: true });
    });
  });
  return lines;
}

type PinPlan = { position: [number, number]; text: string; title: string; placeId: string; backlog: boolean; zIndex: number; unverified: boolean };
type PinRecord = { marker: any; position: [number, number]; text: string; title: string; placeId: string; backlog: boolean; zIndex: number; focus: boolean; unverified: boolean };

function pinLabel(record: PinRecord) {
  const classes = `map-pin${record.backlog ? " backlog-pin" : ""}${record.focus ? " is-focus" : ""}${record.unverified ? " needs-check" : ""}`;
  return { content: `<span class="${classes}">${record.text}</span>`, direction: "center" };
}

type MapViewProps = {
  days: Day[];
  city: string;
  backlog: Stop[];
  showBacklog: boolean;
  focusPlace?: Place | null;
  /** 行程 id：只有换行程时才重新取景，编辑/切天不打断用户的缩放平移。 */
  tripId?: number;
  /** 分享页等双语场景：只翻译地图自身的控件和状态，不改变高德底图语言。 */
  lang?: "zh" | "en";
  /** 分享页另有完整的地图说明时，隐藏地图内右下角的短署名，避免重复。 */
  showCaption?: boolean;
};

function mapStatusText(text: string, en: boolean) {
  if (!en) return text;
  if (text === "正在加载地图…") return "Loading map…";
  if (text === "配置高德地图密钥后显示地图") return "Configure Amap keys to show the map.";
  if (text === "地图加载超时，请重试") return "Map loading timed out. Please try again.";
  if (text === "地图加载失败，请检查网络后重试") return "Map failed to load. Check your network and try again.";
  return text;
}

export function MapView({ days, city, backlog, showBacklog, focusPlace, tripId, lang = "zh", showCaption = true }: MapViewProps) {
  const en = lang === "en";
  const ui = (zh: string, english: string) => (en ? english : zh);
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const pins = useRef(new Map<string, PinRecord>());
  const lines = useRef(new Map<string, LineRecord>());
  const lastFit = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState("正在加载地图…");
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let alive = true;
    let map: any = null;
    setStatus("正在加载地图…");
    setFailed(false);
    (async () => {
      try {
        const AMap = await loadAmap();
        if (!alive || !el.current) return;
        map = new AMap.Map(el.current, { zoom: 11, viewMode: "2D", resizeEnable: true, mapStyle: "amap://styles/whitesmoke" });
        mapRef.current = map;
        lastFit.current = null;
        setReady(true);
        setStatus("");
      } catch (error) {
        if (!alive) return;
        setFailed(true);
        setStatus(message(error));
      }
    })();
    return () => {
      alive = false;
      pins.current.clear();
      lines.current.clear();
      mapRef.current = null;
      lastFit.current = null;
      map?.destroy?.();
    };
  }, [retry]);

  // 覆盖物按 stop.id / 路线 key 增量对齐：只补新增、删多余，不再 clearMap 重建。
  useEffect(() => {
    const map = mapRef.current;
    const AMap = window.AMap;
    if (!ready || !map || !AMap) return;
    const plans = new Map<string, PinPlan>();
    days.forEach((day, dayIndex) => {
      day.stops.forEach((stop, index) => {
        const position = parseLocation(stop.place.location);
        if (!position) return;
        plans.set(`day-${dayIndex}-${stop.place.id}`, {
          position,
          text: days.length > 1 ? `${dayIndex + 1}.${index + 1}` : String(index + 1),
          title: stop.place.name,
          placeId: stop.place.id,
          backlog: false,
          zIndex: 100 + dayIndex,
          unverified: needsCheck(stop.place),
        });
      });
    });
    if (showBacklog) {
      backlog.forEach((stop) => {
        const position = parseLocation(stop.place.location);
        if (!position || plans.has(`backlog-${stop.place.id}`)) return;
        plans.set(`backlog-${stop.place.id}`, { position, text: "待", title: stop.place.name, placeId: stop.place.id, backlog: true, zIndex: 90, unverified: needsCheck(stop.place) });
      });
    }

    const clearIcon = new AMap.Icon({
      image: "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
      size: new AMap.Size(1, 1),
      imageSize: new AMap.Size(1, 1),
    });

    plans.forEach((plan, key) => {
      const existing = pins.current.get(key);
      if (existing) {
        existing.marker.setPosition(plan.position);
        existing.marker.setTitle?.(plan.title);
        if (existing.text !== plan.text || existing.unverified !== plan.unverified) {
          existing.text = plan.text;
          existing.unverified = plan.unverified;
          existing.marker.setLabel(pinLabel(existing));
        }
        return;
      }
      const record: PinRecord = { marker: null, focus: false, ...plan };
      record.marker = new AMap.Marker({
        position: plan.position,
        title: plan.title,
        icon: clearIcon,
        zIndex: plan.zIndex,
        label: pinLabel(record),
      });
      record.marker.setMap(map);
      pins.current.set(key, record);
    });
    pins.current.forEach((record, key) => {
      if (plans.has(key)) return;
      map.remove(record.marker);
      pins.current.delete(key);
    });

    const nextLines = buildRouteLines(days);
    const stroke = routeStrokeColor();
    nextLines.forEach((line, key) => {
      const existing = lines.current.get(key);
      if (existing) {
        // 同一 key 的端点可能随站点调整变化（虚线尤其如此），路径变了就原地更新。
        const pathKey = JSON.stringify(line.path);
        if (existing.pathKey !== pathKey) {
          existing.overlay.setPath?.(line.path);
          existing.pathKey = pathKey;
        }
        return;
      }
      const overlay = line.dashed
        ? new AMap.Polyline({
            path: line.path,
            strokeStyle: "dashed",
            strokeDasharray: [8, 6],
            strokeColor: stroke,
            strokeWeight: 2,
            strokeOpacity: 0.5,
            zIndex: 40,
          })
        : new AMap.Polyline({ path: line.path, strokeColor: stroke, strokeWeight: 3, strokeOpacity: 0.85 });
      overlay.setMap(map);
      lines.current.set(key, { overlay, pathKey: JSON.stringify(line.path) });
    });
    lines.current.forEach((record, key) => {
      if (nextLines.has(key)) return;
      map.remove(record.overlay);
      lines.current.delete(key);
    });
  }, [ready, days, backlog, showBacklog]);

  // 只在换行程时取景一次；用户拖动/缩放后不会被编辑动作打断。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const key = tripId != null ? `trip-${tripId}` : `city-${city}`;
    if (lastFit.current === key) return;
    lastFit.current = key;
    const overlays = [...[...pins.current.values()].map((record) => record.marker), ...[...lines.current.values()].map((record) => record.overlay)];
    if (overlays.length) map.setFitView(overlays, false, [55, 55, 55, 55]);
    else map.setCity(city);
  }, [ready, tripId, city, days, backlog, showBacklog]);

  // 分享页点站点：高亮并定位，找不到对应 pin 时至少把地图移到该点。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focusPlace) return;
    const point = parseLocation(focusPlace.location);
    let focusKey: string | null = null;
    pins.current.forEach((record, key) => {
      const next = record.placeId === focusPlace.id;
      if (next) focusKey = key;
      if (record.focus === next) return;
      record.focus = next;
      record.marker.setLabel(pinLabel(record));
      record.marker.setzIndex?.(next ? 130 : record.zIndex);
    });
    const target = focusKey ? pins.current.get(focusKey)?.position : point;
    if (target) map.setZoomAndCenter(15, target);
  }, [ready, focusPlace]);

  function fitAll() {
    const map = mapRef.current;
    if (!map) return;
    const overlays = [...[...pins.current.values()].map((record) => record.marker), ...[...lines.current.values()].map((record) => record.overlay)];
    if (overlays.length) map.setFitView(overlays, false, [55, 55, 55, 55]);
    else map.setCity(city);
  }

  const hasStops = days.some((day) => day.stops.length > 0) || (showBacklog && backlog.length > 0);

  return (
    <div className="map-wrap">
      <div ref={el} className="map" />
      {status && (
        <div className="map-placeholder" role={failed ? "alert" : "status"}>
          <strong>{mapStatusText(status, en)}</strong>
          <small>{ui("地点与路线信息仍可在行程中查看", "Stops and routes are still available in the itinerary.")}</small>
          {failed && (
            <button type="button" className="secondary map-retry" onClick={() => setRetry((value) => value + 1)}>
              {ui("重试", "Try again")}
            </button>
          )}
        </div>
      )}
      {ready && hasStops && (
        <button
          type="button"
          className="map-reset"
          onClick={fitAll}
          aria-label={ui("回到全览", "Fit all stops")}
        >
          {ui("全览", "Fit all")}
        </button>
      )}
      {showCaption && <div className="map-caption">{ui("地图与路线由高德提供", "Map & routes by Amap")}</div>}
    </div>
  );
}
