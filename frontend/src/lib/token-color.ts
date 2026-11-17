// 令牌值在一次会话内恒定，缓存避免每次同步覆盖物都做一次 DOM 探测。
const resolved = new Map<string, string>();

// 高德覆盖物只接受具体颜色值，这里把 Wayfind 令牌解析成 rgb 再交给 canvas
function tokenColor(name: string, fallback: string): string {
  const cached = resolved.get(name);
  if (cached) return cached;
  const probe = document.createElement("span");
  probe.style.cssText = `display:none;color:var(${name})`;
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  const result = value && value !== "rgba(0, 0, 0, 0)" ? value : fallback;
  resolved.set(name, result);
  return result;
}

/** 地图路线描边色：统一走 accent 令牌，避免各地图各留一份模块级缓存与兜底色。 */
export function routeStrokeColor(): string {
  return tokenColor("--color-accent", "#A8342A");
}
