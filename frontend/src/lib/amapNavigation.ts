import type { Place } from '../types/trip';

export type NavigationMode = 'walk' | 'bus' | 'car';

/** 把行程交通方式映射到高德 URI 的出行方式。 */
export function navigationMode(transport: string): NavigationMode {
  if (transport === 'walking') return 'walk';
  if (transport === 'transit') return 'bus';
  return 'car';
}

/** 高德 URI API：在手机上唤起高德地图 App，未安装时打开高德网页版。 */
export function amapNavigationUrl(place: Pick<Place, 'name' | 'location'> | null, mode: NavigationMode = 'car'): string | null {
  if (!place) return null;
  const [lng, lat] = String(place.location ?? '').split(',').map(Number);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return null;
  const name = encodeURIComponent(place.name?.trim() || '目的地');
  const src = encodeURIComponent('xingji-trip');
  return `https://uri.amap.com/navigation?to=${lng},${lat},${name}&mode=${mode}&policy=1&src=${src}&coordinate=gaode&callnative=1`;
}
