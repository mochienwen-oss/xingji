import { describe, expect, it } from "vitest";
import type { Place } from "../types/trip";
import {
  needsCheck,
  placeVerification,
  verificationCopy,
  verificationStats,
  verificationTitle,
} from "./verification";

function place(overrides: Partial<Place> = {}): Place {
  return {
    id: "p1",
    name: "西湖",
    address: "杭州市西湖区",
    location: "120.15,30.26",
    opentime: "",
    cost: "",
    source_time: "2026-11-07T04:30:00Z",
    ...overrides,
  };
}

describe("verification", () => {
  it("优先使用后端核验字段", () => {
    const result = placeVerification(place({
      opentime: "",
      verification: { status: "verified", source: "amap", checked_at: "2026-11-07T04:30:00Z", opening_hours: true },
    }));
    expect(result.status).toBe("verified");
    expect(result.opening_hours).toBe(true);
    expect(needsCheck(place({ verification: { status: "verified", source: "amap", checked_at: "", opening_hours: true } }))).toBe(false);
  });

  it("标记为已核验却没有营业时间时降级为待确认", () => {
    const result = placeVerification(place({
      verification: { status: "verified", source: "amap", checked_at: "", opening_hours: false },
    }));
    expect(result.status).toBe("needs_check");
    expect(needsCheck(place({ verification: { status: "verified", source: "amap", checked_at: "", opening_hours: false } }))).toBe(true);
  });

  it("旧行程没有核验字段时按 opentime 派生", () => {
    expect(placeVerification(place({ opentime: "09:00-17:00" })).status).toBe("verified");
    expect(placeVerification(place({ opentime: "  " })).status).toBe("needs_check");
    expect(placeVerification(place({ unavailable: true })).status).toBe("unavailable");
  });

  it("汇总按地点 id 去重并统计待确认数量", () => {
    const places = [
      place({ id: "a", opentime: "09:00-17:00" }),
      place({ id: "a", opentime: "09:00-17:00" }),
      place({ id: "b" }),
      place({ id: "c", unavailable: true }),
    ];
    expect(verificationStats(places)).toEqual({
      total: 3,
      verified: 1,
      needsCheck: 1,
      unavailable: 1,
      attention: 2,
    });
    expect(verificationStats([])).toEqual({
      total: 0,
      verified: 0,
      needsCheck: 0,
      unavailable: 0,
      attention: 0,
    });
  });

  it("中英文摘要说清楚核验比例和待确认原因", () => {
    const zh = verificationCopy("zh");
    expect(zh.summaryTitle(3, 5)).toBe("3/5 个地点已核验营业时间");
    expect(zh.summaryAll(5)).toBe("5 个地点已核验营业时间");
    expect(zh.hint(1, 1)).toContain("1 个营业时间待确认");
    expect(zh.hint(1, 1)).toContain("1 个地点暂不可用");
    const en = verificationCopy("en");
    expect(en.summaryTitle(3, 5)).toBe("3/5 places verified");
    expect(en.summaryAll(5)).toBe("All 5 places verified");
    expect(en.hint(1, 0)).toContain("1 need checking");
  });

  it("标记标题包含来源，并把核验时间裁到日期", () => {
    const title = verificationTitle(place({ opentime: "09:00-17:00" }));
    expect(title).toContain("已核验");
    expect(title).toContain("高德地点数据");
    expect(title).toContain("核验于 2026-11-07");
    expect(title).not.toContain("T04:30");
    expect(verificationTitle(place(), "en")).toContain("Hours need checking");
  });
});
