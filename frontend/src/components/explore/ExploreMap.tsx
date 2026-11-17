import { useEffect, useRef, useState } from 'react';
import { loadAmap, type AmapMap, type AmapNamespace } from '../../lib/mapLoader';
import { routeStrokeColor } from '../../lib/token-color';
import type { Place, TripMapView } from '../../types/trip';
import styles from './ExploreMap.module.css';

export type ExploreCenter = {
  lon: number;
  lat: number;
  city: string;
  label: string;
  located: boolean;
  approximate?: boolean;
};

export type ExploreMapProps = {
  center: ExploreCenter | null;
  places: Place[];
  selectedId: string | null;
  tripView: TripMapView | null;
  focus: { place: Place; token: number } | null;
  locateToken: number;
  onLocated: (center: ExploreCenter) => void;
  onLocationError: (message: string) => void;
  onSelect: (place: Place) => void;
  onReady?: () => void;
};

type NearbyRecord = { marker: AmapMap; element: HTMLButtonElement; place: Place };
type TripRecord = { marker: AmapMap; element: HTMLDivElement };

const MAP_PLACE_LIMIT = 20;
const LOCATION_PATTERN = /^\s*-?\d{1,3}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?\s*$/;
const LOCATION_FALLBACK = '定位未成功，请检查设备及浏览器定位权限，或搜索城市';

function parseLocation(value: string | null | undefined): [number, number] | null {
  if (!value || !LOCATION_PATTERN.test(value)) return null;
  const [lng, lat] = value.split(',').map(Number);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return null;
  return [lng, lat];
}

/** 高德地图是命令式实例：React 只负责数据和覆盖物的差量同步。 */
export function ExploreMap({
  center,
  places,
  selectedId,
  tripView,
  focus,
  locateToken,
  onLocated,
  onLocationError,
  onSelect,
  onReady,
}: ExploreMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<AmapMap | null>(null);
  const nearbyRef = useRef(new Map<string, NearbyRecord>());
  const tripRef = useRef(new Map<string, TripRecord>());
  const centerRef = useRef<AmapMap | null>(null);
  const routeRef = useRef(new Map<string, AmapMap>());
  const routeKeyRef = useRef<string | null | undefined>(null);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const syncPinLabelsRef = useRef<() => void>(() => {});
  const callbacks = useRef({ onLocated, onLocationError, onSelect, onReady });
  callbacks.current = { onLocated, onLocationError, onSelect, onReady };

  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  // 地图是命令式画布：pin 名称靠近右缘时把标签翻到圆点左侧，避免被画布裁掉。
  const syncPinLabels = () => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container || !map.lngLatToContainer) return;
    const width = container.clientWidth;
    nearbyRef.current.forEach((record) => {
      const position = parseLocation(record.place.location);
      if (!position) return;
      const point = map.lngLatToContainer(position);
      const label = record.element.querySelector<HTMLElement>('[data-pin-label]');
      if (!point || !label) return;
      const overflow = point.x + 10 + (label.offsetWidth || 0) > width - 8;
      record.element.classList.toggle(styles.flip, overflow);
    });
  };
  syncPinLabelsRef.current = syncPinLabels;

  useEffect(() => {
    let cancelled = false;
    let instance: AmapMap | null = null;
    setReady(false);
    setError('');

    void loadAmap()
      .then((amap: AmapNamespace) => {
        if (cancelled || !containerRef.current) return;
        instance = new amap.Map(containerRef.current, {
          zoom: 5,
          center: [116, 25],
          viewMode: '2D',
          resizeEnable: true,
          mapStyle: 'amap://styles/whitesmoke',
        });
        mapRef.current = instance;
        setReady(true);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(reason instanceof Error && reason.message ? reason.message : '请检查网络后重试');
      });

    return () => {
      cancelled = true;
      nearbyRef.current.clear();
      tripRef.current.clear();
      routeRef.current.clear();
      centerRef.current = null;
      instance?.destroy?.();
      if (mapRef.current === instance) mapRef.current = null;
      setReady(false);
    };
  }, [reload]);

  useEffect(() => {
    if (ready) callbacks.current.onReady?.();
  }, [ready]);

  // 附近地点：最多 20 个 pin，按 place.id 复用，只有新增/删除才动 DOM。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const visible = places.slice(0, MAP_PLACE_LIMIT);
    const wanted = new Set(visible.map((place) => place.id));

    visible.forEach((place) => {
      const position = parseLocation(place.location);
      if (!position) return;
      const existing = nearbyRef.current.get(place.id);
      if (existing) {
        existing.place = place;
        existing.marker.setPosition?.(position);
        existing.element.title = place.name;
        existing.element.setAttribute('aria-label', `查看${place.name}`);
        const label = existing.element.querySelector('span:last-child');
        if (label) label.textContent = place.name;
        return;
      }

      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = styles.pin;
      pin.title = place.name;
      pin.setAttribute('aria-label', `查看${place.name}`);
      const dot = document.createElement('span');
      dot.className = styles.pinDot;
      dot.setAttribute('aria-hidden', 'true');
      const name = document.createElement('span');
      name.className = styles.pinName;
      name.dataset.pinLabel = '1';
      name.textContent = place.name;
      pin.append(dot, name);
      const record: NearbyRecord = { marker: null, element: pin, place };
      pin.addEventListener('click', (event) => {
        event.stopPropagation();
        callbacks.current.onSelect(record.place);
      });
      const selected = place.id === selectedRef.current;
      pin.classList.toggle(styles.selected, selected);
      const marker = new window.AMap.Marker({
        position,
        content: pin,
        anchor: 'center',
        zIndex: selected ? 105 : 100,
      });
      marker.setMap(map);
      record.marker = marker;
      nearbyRef.current.set(place.id, record);
    });

    window.requestAnimationFrame(() => syncPinLabelsRef.current());

    nearbyRef.current.forEach((record, id) => {
      if (wanted.has(record.place.id)) return;
      map.remove(record.marker);
      nearbyRef.current.delete(id);
    });
  }, [ready, places]);

  useEffect(() => {
    if (!ready) return;
    nearbyRef.current.forEach((record, id) => {
      const selected = id === selectedId;
      record.element.classList.toggle(styles.selected, selected);
      record.marker.setzIndex?.(selected ? 105 : 100);
    });
    syncPinLabelsRef.current();
  }, [ready, selectedId]);

  // 平移/缩放/尺寸变化后重新判断标签方向；rAF 合并连续事件，避免抖动。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let frame = 0;
    const schedule = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => syncPinLabelsRef.current());
    };
    const events = ['moveend', 'zoomend', 'resize'];
    events.forEach((event) => map.on?.(event, schedule));
    schedule();
    return () => {
      window.cancelAnimationFrame(frame);
      events.forEach((event) => map.off?.(event, schedule));
    };
  }, [ready]);

  // 城市中心点：只做视觉锚点，颜色交给 CSS Module。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (centerRef.current) {
      map.remove(centerRef.current);
      centerRef.current = null;
    }
    if (!center) return;
    const dot = document.createElement('div');
    dot.className = center.approximate ? styles.cityCenter : styles.positionDot;
    dot.setAttribute('aria-hidden', 'true');
    const marker = new window.AMap.Marker({
      position: [center.lon, center.lat],
      content: dot,
      anchor: 'center',
      zIndex: 99,
    });
    marker.setMap(map);
    centerRef.current = marker;
  }, [ready, center?.lon, center?.lat, center?.approximate]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !center) return;
    map.setZoomAndCenter?.(13, [center.lon, center.lat]);
  }, [ready, center?.lon, center?.lat]);

  // 行程 pins：预览和服务端行程共用；预览用 created_at 作为取景 epoch。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const wanted = new Map<string, { position: [number, number]; text: string; title: string }>();
    if (tripView) {
      tripView.days.forEach((day, dayIndex) => {
        day.stops.forEach((stop, stopIndex) => {
          const position = parseLocation(stop.place.location);
          if (!position) return;
          wanted.set(`trip-${dayIndex}-${stop.place.id}`, {
            position,
            text: tripView.days.length > 1 ? `${dayIndex + 1}.${stopIndex + 1}` : String(stopIndex + 1),
            title: stop.place.name,
          });
        });
      });
      if (tripView.showBacklog) {
        (tripView.backlog || []).forEach((stop) => {
          const position = parseLocation(stop.place.location);
          if (!position) return;
          const key = `backlog-${stop.place.id}`;
          if (wanted.has(key)) return;
          wanted.set(key, { position, text: '待', title: stop.place.name });
        });
      }
    }

    wanted.forEach((item, key) => {
      const existing = tripRef.current.get(key);
      if (existing) {
        existing.marker.setPosition?.(item.position);
        if (existing.element.textContent !== item.text) existing.element.textContent = item.text;
        return;
      }
      const pin = document.createElement('div');
      pin.className = key.startsWith('backlog-') ? `${styles.tripPin} ${styles.backlogPin}` : styles.tripPin;
      pin.textContent = item.text;
      pin.title = item.title;
      const marker = new window.AMap.Marker({
        position: item.position,
        content: pin,
        anchor: 'center',
        zIndex: key.startsWith('backlog-') ? 104 : 106,
      });
      marker.setMap(map);
      tripRef.current.set(key, { marker, element: pin });
    });

    tripRef.current.forEach((record, key) => {
      if (wanted.has(key)) return;
      map.remove(record.marker);
      tripRef.current.delete(key);
    });
  }, [ready, tripView?.previewKey, tripView?.showBacklog, tripView?.days]);

  // 路线：新预览逐段“画”出来，生成时用户能看着路线在地图上连成线；
  // 之后编辑行程（加站）只刷新线条，不重播动画；reduced-motion 时一次画完。
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return undefined;
    const timers: number[] = [];
    const clearRoutes = () => {
      timers.forEach((id) => window.clearTimeout(id));
      timers.length = 0;
      routeRef.current.forEach((line) => {
        try {
          map.remove(line);
        } catch {
          // 地图销毁后覆盖物随实例回收，清不掉也不影响下一次绘制。
        }
      });
      routeRef.current.clear();
    };
    clearRoutes();
    if (!tripView) {
      routeKeyRef.current = null;
      return clearRoutes;
    }
    const segments: { key: string; path: number[][] }[] = [];
    tripView.days.forEach((day, dayIndex) => {
      day.routes.forEach((route, routeIndex) => {
        route.polyline.forEach((path, pathIndex) => {
          if (!Array.isArray(path) || path.length < 2) return;
          segments.push({ key: `route-${dayIndex}-${routeIndex}-${pathIndex}`, path });
        });
      });
    });
    const firstLook = routeKeyRef.current !== tripView.previewKey;
    routeKeyRef.current = tripView.previewKey;
    if (segments.length) {
      const reduceMotion = window.matchMedia
        ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
        : false;
      const step = reduceMotion || !firstLook
        ? 0
        : Math.max(50, Math.min(120, Math.round(1600 / segments.length)));
      segments.forEach((segment, index) => {
        const line = new window.AMap.Polyline({
          path: segment.path,
          strokeColor: routeStrokeColor(),
          strokeWeight: 3,
          strokeOpacity: 0.85,
          zIndex: 50,
        });
        routeRef.current.set(segment.key, line);
        const delay = step <= 0 ? 0 : 160 + index * step;
        if (delay <= 0) {
          line.setMap(map);
          return;
        }
        timers.push(window.setTimeout(() => line.setMap(map), delay));
      });
    }
    return clearRoutes;
  }, [ready, tripView?.previewKey, tripView?.days]);

  // 取景：优先框住行程；否则框住附近的 pin。地图若被抽屉盖住下半屏，先取景再整体上移。
  useEffect(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!ready || !map || !container) return;
    const tripOverlays = Array.from(tripRef.current.values()).map((record) => record.marker);
    const nearbyOverlays = Array.from(nearbyRef.current.values()).map((record) => record.marker);
    const overlays = tripOverlays.length ? tripOverlays : nearbyOverlays;
    if (!overlays.length) return;
    const height = container.clientHeight;
    // 行程页的内嵌地图只有约 200px 高；只有全屏探索地图才会被抽屉压住下半屏。
    const inline = height > 0 && height < 500;
    const maxZoom = tripOverlays.length ? 15 : 16;
    const timer = window.setTimeout(() => {
      try {
        if (inline) {
          map.setFitView?.(overlays, true, [24, 24, 24, 24], maxZoom);
          return;
        }
        map.setFitView?.(overlays, true, [78, 56, 56, 56], maxZoom);
        // 底部大 padding 在部分版本会算出错误视野，改为取景后整体上移半个抽屉高度。
        const sheet = Math.min(window.innerHeight * 0.46, 560);
        map.panBy?.(0, -Math.round(sheet / 2), true);
      } catch {
        // 地图尺寸尚未就绪时下次数据变化会再试。
      }
    }, 120);
    return () => window.clearTimeout(timer);
  }, [ready, tripView?.previewKey, places]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    const position = parseLocation(focus.place.location);
    if (position) map.setZoomAndCenter?.(15, position);
  }, [ready, focus?.token]);

  // 定位只由 locateToken 触发；挂载时绝不自动请求，避免反复弹权限。
  useEffect(() => {
    if (!ready || locateToken <= 0) return;
    let active = true;
    let completed = false;
    const unavailable = window.isSecureContext
      ? LOCATION_FALLBACK
      : '当前地址无法精确定位，请搜索城市或在 HTTPS 下打开';
    const timeout = window.setTimeout(() => {
      if (!active || completed) return;
      completed = true;
      callbacks.current.onLocationError(unavailable);
    }, 18000);

    const finish = (next: ExploreCenter) => {
      if (!active || completed) return;
      completed = true;
      window.clearTimeout(timeout);
      callbacks.current.onLocated(next);
    };
    const fail = () => {
      if (!active || completed) return;
      completed = true;
      window.clearTimeout(timeout);
      callbacks.current.onLocationError(unavailable);
    };

    const cityFallback = () => {
      window.AMap.plugin('AMap.CitySearch', () => {
        if (!active || completed) return;
        new window.AMap.CitySearch().getLocalCity(async (state: string, result: { city?: string }) => {
          if (!active || completed) return;
          const city = state === 'complete' && typeof result?.city === 'string' ? result.city : '';
          if (!city) {
            fail();
            return;
          }
          try {
            const found = await window.fetch(`/api/discover/city-center?city=${encodeURIComponent(city)}`).then((response) => {
              if (!response.ok) throw new Error('city-center');
              return response.json() as Promise<{ lon: number; lat: number; city: string }>;
            });
            if (!active || completed) return;
            finish({ ...found, label: `${found.city} · 按网络推测的城市中心`, located: false, approximate: true });
          } catch {
            fail();
          }
        });
      });
    };

    if (!window.isSecureContext) {
      cityFallback();
      return () => {
        active = false;
        window.clearTimeout(timeout);
      };
    }

    window.AMap.plugin('AMap.Geolocation', () => {
      if (!active) return;
      const geolocation = new window.AMap.Geolocation({
        enableHighAccuracy: true,
        timeout: 10000,
        showButton: false,
        showMarker: false,
        showCircle: false,
        extensions: 'all',
      });
      geolocation.getCurrentPosition((state: string, result: {
        position?: { lng: number; lat: number };
        location_type?: string;
        addressComponent?: { city?: string; province?: string };
      }) => {
        if (!active || completed) return;
        const type = String(result?.location_type || '').toLowerCase();
        if (state === 'complete' && result?.position && !type.includes('ip')) {
          const lon = Number(result.position.lng);
          const lat = Number(result.position.lat);
          if (Number.isFinite(lon) && Number.isFinite(lat) && lon >= 73 && lon <= 135 && lat >= 3 && lat <= 54) {
            const address = result.addressComponent || {};
            const city = typeof address.city === 'string' && address.city
              ? address.city
              : typeof address.province === 'string' ? address.province : '';
            finish({ lon, lat, city, label: city || '定位位置', located: true });
            return;
          }
        }
        cityFallback();
      });
    });

    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [ready, locateToken]);

  return (
    <div className={styles.shell}>
      <div ref={containerRef} className={styles.canvas} data-testid="explore-map" />
      {!ready && !error ? (
        <div className={styles.loading} role="status">正在加载地图</div>
      ) : null}
      {error ? (
        <div className={styles.error} role="alert">
          <p className={styles.errorTitle}>地图暂时没加载出来</p>
          <p className={styles.errorBody}>{error}</p>
          <button type="button" className={styles.retry} onClick={() => setReload((value) => value + 1)}>
            重试
          </button>
        </div>
      ) : null}
      <div className={styles.attribution}>地图与地点由高德提供</div>
    </div>
  );
}