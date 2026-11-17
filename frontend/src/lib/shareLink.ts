/** 分享链接格式与展示裁剪：生成用 /s/{token}（可被微信/X 抓取），解析兼容旧 #share=。 */

const HASH_MARKER = "#share=";
const PATH_MARKER = "/s/";

export function shareUrl(token: string, origin = window.location.origin) {
  return `${origin}${PATH_MARKER}${encodeURIComponent(token)}`;
}

export function shareToken(value: string): string {
  const hashIndex = value.indexOf(HASH_MARKER);
  if (hashIndex >= 0) {
    const raw = value.slice(hashIndex + HASH_MARKER.length);
    const end = raw.search(/[?#]/);
    return decodeURIComponent(end >= 0 ? raw.slice(0, end) : raw);
  }
  const match = value.match(/\/s\/([^/?#]+)/);
  if (!match) return "";
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** 只展示可辨认的首尾，完整链接由「复制」按钮写入剪贴板。 */
export function maskShareLink(value: string): string {
  const token = shareToken(value);
  if (!token) return value;
  const masked = token.length <= 16 ? token : `${token.slice(0, 8)}…${token.slice(-4)}`;
  const hashIndex = value.indexOf(HASH_MARKER);
  if (hashIndex >= 0) return `${value.slice(0, hashIndex + HASH_MARKER.length)}${masked}`;
  const pathIndex = value.indexOf(PATH_MARKER);
  if (pathIndex >= 0) return `${value.slice(0, pathIndex + PATH_MARKER.length)}${masked}`;
  return value;
}
