import { describe, expect, it } from "vitest";
import type { Day, Place, Stop } from "../types/trip";
import {
  parseOpenDays,
  runItineraryChecks,
  startDateForDay,
  weekdayMon,
} from "./itineraryCheck";

function place(overrides: Partial<Place> = {}): Place {
  return {
    id: "p1",
    name: "杭州博物馆",
    address: "",
    location: "120.166525,30.239091",
    opentime: "",
    cost: "",
    source_time: "",
    verification: { status: "verified", source: "amap", checked_at: "2026-11-07T00:00:00Z", opening_hours: true },
    ...overrides,
  };
}

function stop(overrides: Partial<Stop> = {}): Stop {
  return { place: place(), duration: 60, reason: "", ...overrides };
}

function day(stops: Stop[]): Day {
  return { stops, routes: [] };
}

describe("parseOpenDays", () => {
  it("parses a weekday list with an explicit closed day", () => {
    const days = parseOpenDays("全年 周一, 周三–周日 09:00–16:30开放 最晚进入16:30");
    expect(days ? [...days] : null).toEqual([1, 3, 4, 5, 6, 7]);
  });

  it("parses a closed-day segment followed by open days", () => {
    const days = parseOpenDays("周一 全天关闭；周二至周日 09:30-17:00 最晚进入16:30");
    expect(days ? [...days] : null).toEqual([2, 3, 4, 5, 6, 7]);
  });

  it("parses seasonal prefixes and the every-day case", () => {
    expect([...(parseOpenDays("4月1日至10月31日 周二至周日 09:00-17:00开放") ?? [])]).toEqual([2, 3, 4, 5, 6, 7]);
    expect([...(parseOpenDays("周一至周日 09:00-21:00") ?? [])]).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("returns null when there is no explicit weekday/hour combination", () => {
    expect(parseOpenDays("")).toBeNull();
    expect(parseOpenDays("周一闭馆")).toBeNull();
    expect(parseOpenDays("09:00-17:00")).toBeNull();
  });
});

describe("startDateForDay", () => {
  it("adds days in local time and maps Sunday to 7", () => {
    const monday = startDateForDay("2026-11-09", 0);
    expect(monday).not.toBeNull();
    expect(weekdayMon(monday as Date)).toBe(1);
    const sunday = startDateForDay("2026-11-09", 6);
    expect(weekdayMon(sunday as Date)).toBe(7);
    expect(startDateForDay(null, 0)).toBeNull();
    expect(startDateForDay("待定", 0)).toBeNull();
  });
});

describe("runItineraryChecks", () => {
  it("warns when the start date lands on a fixed closing day", () => {
    const checks = runItineraryChecks({
      days: [day([stop({ place: place({ opentime: "周一 全天关闭；周二至周日 09:30-17:00" }) })])],
      request: { start_date: "2026-11-09" },
    });
    expect(checks).toHaveLength(1);
    expect(checks[0]).toMatchObject({ code: "closed_day", day: 1, weekday: 1 });
  });

  it("lists fixed closing days when the date is not set", () => {
    const checks = runItineraryChecks({
      days: [day([stop()])],
      request: { start_date: null },
    });
    expect(checks).toHaveLength(0);
    const withClosedDay = runItineraryChecks({
      days: [day([stop({ place: place({ opentime: "全年 周一, 周三–周日 09:00–16:30" }) })])],
      request: { start_date: null },
    });
    expect(withClosedDay[0]).toMatchObject({
      code: "weekly_closure",
      places: [{ name: "杭州博物馆", closedDays: [2] }],
    });
  });

  it("flags a packed day and a long straight-line hop", () => {
    const packed = runItineraryChecks({
      days: [day(Array.from({ length: 7 }, (_, index) => stop({ place: place({ id: "p" + index, name: "点" + index }) })))],
    });
    expect(packed.some(check => check.code === "heavy_day")).toBe(true);

    const longHop = runItineraryChecks({
      days: [day([
        stop({ place: place({ id: "a", name: "A", location: "120.10,30.20" }) }),
        stop({ place: place({ id: "b", name: "B", location: "120.70,30.20" }) }),
      ])],
    });
    expect(longHop[0]).toMatchObject({ code: "long_hop", day: 1 });
  });

  it("flags the same place appearing on different days", () => {
    const checks = runItineraryChecks({
      days: [day([stop()]), day([stop()])],
    });
    expect(checks[0]).toMatchObject({ code: "duplicate_place", name: "杭州博物馆", count: 2 });
  });
});
