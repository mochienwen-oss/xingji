/** 共享的地理换算：行程体检的距离核对靠它，避免坐标解析与距离公式各写一份。 */

export type GeoPoint = [number, number];

/** 解析后端存的高德坐标 "lng,lat"；缺值或非数字返回 null。 */
export function parseLocation(location: string | null | undefined): GeoPoint | null {
  const parts = (location || '').split(',');
  if (parts.length < 2) return null;
  // 空分量必须按缺值处理：Number('') 和 Number(' ') 都是 0，否则 "120.15," 会被当成
  // "120.15,0" 这种不存在的坐标，在体检里算出上万公里、在时间估算里变成几小时路段。
  if (!parts[0].trim() || !parts[1].trim()) return null;
  const lng = Number(parts[0]);
  const lat = Number(parts[1]);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  // 超出经纬度合法范围的同样不是可以参与距离计算的坐标。
  if (Math.abs(lng) > 180 || Math.abs(lat) > 90) return null;
  return [lng, lat];
}

/** 两点球面直线距离（公里）。 */
export function straightLineKm(from: GeoPoint, to: GeoPoint): number {
  const rad = (value: number) => (value * Math.PI) / 180;
  const dLat = rad(to[1] - from[1]);
  const dLng = rad(to[0] - from[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(from[1])) * Math.cos(rad(to[1])) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** 从 "lng,lat" 字符串直接算直线距离；任一端无法解析时返回 null。 */
export function distanceKmBetween(from: string, to: string): number | null {
  const a = parseLocation(from);
  const b = parseLocation(to);
  if (!a || !b) return null;
  return straightLineKm(a, b);
}
