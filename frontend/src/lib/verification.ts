import type { Place, PlaceVerification } from "../types/trip";

export type VerificationLang = "zh" | "en";
export type VerificationStatus = PlaceVerification["status"];

export type VerificationStats = {
  total: number;
  verified: number;
  needsCheck: number;
  unavailable: number;
  /** 需要提醒用户出发前确认的地点数量。 */
  attention: number;
};

const STATUSES: VerificationStatus[] = ["verified", "needs_check", "unavailable"];

/**
 * 地点核验状态只有一个来源：后端回填的 verification。
 * 旧行程/旧接口没有该字段时按 opentime 派生，保证所有页面口径一致。
 */
export function placeVerification(place: Place): PlaceVerification {
  const raw = place.verification;
  if (raw && STATUSES.includes(raw.status)) {
    const opening = raw.opening_hours === true && raw.status !== "unavailable";
    return {
      status: raw.status === "verified" && !opening ? "needs_check" : raw.status,
      source: typeof raw.source === "string" ? raw.source : "amap",
      checked_at: typeof raw.checked_at === "string" ? raw.checked_at : "",
      opening_hours: opening,
    };
  }
  if (place.unavailable) {
    return { status: "unavailable", source: "amap", checked_at: place.source_time || "", opening_hours: false };
  }
  const opening = Boolean(place.opentime?.trim());
  return {
    status: opening ? "verified" : "needs_check",
    source: "amap",
    checked_at: place.source_time || "",
    opening_hours: opening,
  };
}

export function needsCheck(place: Place): boolean {
  return placeVerification(place).status !== "verified";
}

/** 汇总整段行程；同一地点跨天重复出现只算一次。 */
export function verificationStats(places: Place[]): VerificationStats {
  const seen = new Set<string>();
  const stats: VerificationStats = { total: 0, verified: 0, needsCheck: 0, unavailable: 0, attention: 0 };
  for (const place of places) {
    const id = place.id || place.name;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    stats.total += 1;
    const status = placeVerification(place).status;
    if (status === "verified") stats.verified += 1;
    else if (status === "unavailable") stats.unavailable += 1;
    else stats.needsCheck += 1;
  }
  stats.attention = stats.needsCheck + stats.unavailable;
  return stats;
}

export type VerificationCopy = {
  verified: string;
  needsCheck: string;
  unavailable: string;
  summaryTitle: (verified: number, total: number) => string;
  summaryAll: (total: number) => string;
  hint: (needsCheck: number, unavailable: number) => string;
  hintAll: string;
  sourceAmap: string;
  checkedAt: (value: string) => string;
};

const COPY: Record<VerificationLang, VerificationCopy> = {
  zh: {
    verified: "已核验",
    needsCheck: "营业时间待确认",
    unavailable: "地点暂不可用",
    summaryTitle: (verified, total) => `${verified}/${total} 个地点已核验营业时间`,
    summaryAll: (total) => `${total} 个地点已核验营业时间`,
    hint: (needsCheck, unavailable) => {
      const parts: string[] = [];
      if (needsCheck) parts.push(`${needsCheck} 个营业时间待确认`);
      if (unavailable) parts.push(`${unavailable} 个地点暂不可用`);
      return `${parts.join(" · ")}，出发前建议查看官方公告。`;
    },
    hintAll: "地点与时间来自高德，出发前仍建议查看官方公告。",
    sourceAmap: "高德地点数据",
    checkedAt: (value) => `核验于 ${value}`,
  },
  en: {
    verified: "Verified",
    needsCheck: "Hours need checking",
    unavailable: "Place unavailable",
    summaryTitle: (verified, total) => `${verified}/${total} places verified`,
    summaryAll: (total) => `All ${total} places verified`,
    hint: (needsCheck, unavailable) => {
      const parts: string[] = [];
      if (needsCheck) parts.push(`${needsCheck} need checking`);
      if (unavailable) parts.push(`${unavailable} unavailable`);
      return `${parts.join(" · ")}. Please confirm before you go.`;
    },
    hintAll: "Places and hours come from Amap. Still worth a quick official check before you go.",
    sourceAmap: "Amap place data",
    checkedAt: (value) => `Checked ${value}`,
  },
};

export function verificationCopy(lang: VerificationLang = "zh"): VerificationCopy {
  return COPY[lang];
}

function shortDate(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value);
  return match ? match[1] : value;
}

export function verificationTitle(place: Place, lang: VerificationLang = "zh"): string {
  const verification = placeVerification(place);
  const copy = verificationCopy(lang);
  const source = verification.source === "amap" ? copy.sourceAmap : verification.source;
  const status = verification.status === "verified"
    ? copy.verified
    : verification.status === "unavailable"
      ? copy.unavailable
      : copy.needsCheck;
  const checked = verification.checked_at ? ` · ${copy.checkedAt(shortDate(verification.checked_at))}` : "";
  return `${status} · ${source}${checked}`;
}
