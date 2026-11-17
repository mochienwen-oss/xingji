import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Day, Place, Route, Stop, Trip } from "../types/trip";
import { buildTodayCache, clearAllTodayCaches, readTodayCache, saveTodayCache } from "./todayCache";

/**
 * 需求出处：README.md:102「todayCache 只缓存今天这一天、只读快照」、
 * B5 需求、README.md:108（缺失时显示未知）。
 * 关键规则：
 * - 只为「今天」写快照；未出发、已结束、写错 dayIndex 都不写，或写了也读不回来；
 * - 跨零点后旧快照立即失效（0.3.0 日期守卫），不能把昨天的行程当今天展示；
 * - 只存标题/城市/这一天站点/导航链接，不存完整行程、同行人、对话或候选清单；
 * - 名称/地址/站点数有上限，导航链接只接受高德 uri；坏数据静默返回 null；
 * - 退出登录清掉所有行程的今日缓存。
 */

const KEY = "xingji.today.v1.";
const NOW = new Date(2026, 10, 7, 10, 0); // 2026-11-07 周六

function place(id: string, name: string, location = "120.15,30.25"): Place {
  return { id, name, address: name + "地址", location, opentime: "", cost: "", source_time: "" };
}

function stop(id: string, name: string, duration = 60, location = "120.15,30.25"): Stop {
  return { place: place(id, name, location), duration, reason: "" };
}

function route(origin: string, destination: string, seconds: number): Route {
  return { origin, destination, mode: "transit", duration: seconds, distance: 5000, polyline: [], source_time: "" };
}

function day(stops: Stop[] = [], routes: Route[] = [], startTime: string | null = "09:00"): Day {
  return { start_time: startTime, end_time: "18:00", stops, routes };
}

function trip(options: {
  id?: number;
  startDate?: string | null;
  days?: number;
  transport?: string;
  title?: string;
  city?: string;
  backlog?: Stop[];
} = {}): Trip {
  const count = options.days ?? 3;
  return {
    id: options.id ?? 7,
    title: options.title ?? "杭州三日",
    request: {
      city: options.city ?? "杭州",
      days: count,
      start_date: options.startDate === undefined ? "2026-11-07" : options.startDate,
      travelers: 2,
      interests: "",
      pace: "适中",
      budget: "",
      must_visit: "",
      transport: options.transport ?? "transit",
    },
    days: Array.from({ length: count }, () => day()),
    backlog: options.backlog ?? [],
  };
}

function sampleDay(): Day {
  return day([stop("a", "西湖", 120), stop("b", "灵隐寺", 90)]);
}

describe("只缓存今天（README:102 / launch-plan:130 日期守卫）", () => {
  beforeEach(() => localStorage.clear());

  it("行程未开始、今天不是该天、行程已结束时都不写快照", () => {
    const source = trip({ days: 3 });
    expect(buildTodayCache(source, 0, day(), NOW)).not.toBeNull();

    // 今天（11-07）只对应第一天的 dayIndex 0。
    expect(buildTodayCache(source, 1, day(), NOW)).toBeNull();
    expect(buildTodayCache(source, 2, day(), NOW)).toBeNull();
    expect(saveTodayCache(source, 1, day(), NOW)).toBeNull();

    // 未出发（11-06）与三天行程已结束（11-10）都不能写出今天快照。
    expect(buildTodayCache(source, 0, day(), new Date(2026, 10, 6, 10, 0))).toBeNull();
    expect(buildTodayCache(source, 0, day(), new Date(2026, 10, 10, 10, 0))).toBeNull();
  });

  it("读侧跨零点立即失效，第二天由新一天的快照接手", () => {
    const source = trip({ days: 3 });
    const lateNight = new Date(2026, 10, 7, 23, 50);
    expect(saveTodayCache(source, 0, sampleDay(), lateNight)).not.toBeNull();
    expect(readTodayCache(7, new Date(2026, 10, 7, 23, 59))).not.toBeNull();
    expect(readTodayCache(7, new Date(2026, 10, 8, 0, 10))).toBeNull();

    // 四天行程的第二天：11-08 写入 dayIndex 1，当天可读，11-09 之后失效。
    const fourDays = trip({ days: 4 });
    expect(saveTodayCache(fourDays, 1, sampleDay(), new Date(2026, 10, 8, 9, 0))).not.toBeNull();
    expect(readTodayCache(7, new Date(2026, 10, 8, 20, 0))?.dayIndex).toBe(1);
    expect(readTodayCache(7, new Date(2026, 10, 9, 0, 5))).toBeNull();
  });

  it("同一天内不同时刻读到的还是同一份快照，savedAt 是写入时间", () => {
    const source = trip();
    const morning = new Date(2026, 10, 7, 8, 0);
    const saved = saveTodayCache(source, 0, sampleDay(), morning);
    expect(saved?.savedAt).toBe(morning.toISOString());

    const read = readTodayCache(7, new Date(2026, 10, 7, 18, 30));
    expect(read).not.toBeNull();
    expect(read?.startDate).toBe("2026-11-07");
    expect(read?.dayIndex).toBe(0);
    expect(read?.savedAt).toBe(morning.toISOString());
  });
});

describe("快照只存今天需要的最小信息（README:102 只读快照）", () => {
  beforeEach(() => localStorage.clear());

  it("顶层与站点字段都在白名单内，不含候选清单或对话", () => {
    const secret = stop("x", "私密候选地点", 30);
    const source = trip({ backlog: [secret], title: "杭州三日", city: "杭州" });
    const cache = buildTodayCache(source, 0, sampleDay(), NOW);
    expect(cache).not.toBeNull();
    if (!cache) throw new Error("expected cache");

    expect(Object.keys(cache).sort()).toEqual([
      "city",
      "dayIndex",
      "savedAt",
      "startDate",
      "stops",
      "title",
      "transport",
      "tripId",
      "v",
    ]);
    expect(Object.keys(cache.stops[0]).sort()).toEqual([
      "address",
      "duration",
      "name",
      "navigationUrl",
      "time",
    ]);
    const json = JSON.stringify(cache);
    expect(json).not.toContain("私密候选地点");
    expect(json).not.toContain("backlog");
    expect(json).not.toContain("conversation");
    expect(cache.v).toBe(1);
    expect(cache.tripId).toBe(7);
    expect(cache.city).toBe("杭州");
  });

  it("导航链接只接受高德 uri，非法坐标与篡改的链接都不会展示", () => {
    const source = trip({
      transport: "transit",
    });
    const weird = day([
      stop("a", "空坐标", 30, ""),
      stop("b", "字母坐标", 30, "abc"),
      stop("c", "缺一项", 30, "120.15"),
      stop("d", "经度超界", 30, "500,30"),
      stop("e", "纬度超界", 30, "120.15,100"),
    ]);
    const cache = buildTodayCache(source, 0, weird, NOW);
    expect(cache?.stops.map(item => item.navigationUrl)).toEqual([null, null, null, null, null]);

    const valid = day([stop("a", "西湖", 60, "120.15,30.25")]);
    const transit = buildTodayCache(trip({ transport: "transit" }), 0, valid, NOW);
    expect(transit?.stops[0].navigationUrl).toMatch(/^https:\/\/uri\.amap\.com\/navigation/);
    expect(transit?.stops[0].navigationUrl).toContain("mode=bus");
    const walking = buildTodayCache(trip({ transport: "walking" }), 0, valid, NOW);
    expect(walking?.stops[0].navigationUrl).toContain("mode=walk");
    const driving = buildTodayCache(trip({ transport: "driving" }), 0, valid, NOW);
    expect(driving?.stops[0].navigationUrl).toContain("mode=car");

    // 被改写成非高德地址的缓存条目按未知处理，但快照本身仍然可读。
    const original = buildTodayCache(trip(), 0, sampleDay(), NOW);
    expect(original).not.toBeNull();
    const tampered = JSON.parse(JSON.stringify(original)) as typeof original;
    if (!tampered) throw new Error("expected cache");
    tampered.stops[0].navigationUrl = "http://evil.example/x";
    localStorage.setItem(KEY + 7, JSON.stringify(tampered));
    const read = readTodayCache(7, NOW);
    expect(read).not.toBeNull();
    expect(read?.stops[0].navigationUrl).toBeNull();
    expect(read?.stops[0].name).toBe("西湖");
  });

  it("站点最多 40 个，名称与地址按上限截断", () => {
    const many = Array.from({ length: 41 }, (_, index) => stop("s" + index, "站点" + index, 30));
    const cache = buildTodayCache(trip(), 0, day(many), NOW);
    expect(cache?.stops).toHaveLength(40);
    expect(saveTodayCache(trip(), 0, day(many), NOW)).not.toBeNull();
    expect(readTodayCache(7, NOW)?.stops).toHaveLength(40);

    const longName = "名".repeat(300);
    const longAddress = "址".repeat(300);
    const longStop: Stop = {
      place: { id: "long", name: longName, address: longAddress, location: "120.15,30.25", opentime: "", cost: "", source_time: "" },
      duration: 60,
      reason: "",
    };
    const truncated = buildTodayCache(trip(), 0, day([longStop]), NOW);
    expect(truncated?.stops[0].name).toHaveLength(80);
    expect(truncated?.stops[0].address).toHaveLength(200);
    saveTodayCache(trip(), 0, day([longStop]), NOW);
    expect(readTodayCache(7, NOW)?.stops[0].name).toHaveLength(80);

    // 超过 40 站的数据被视为损坏，整份快照不展示。
    const original = buildTodayCache(trip(), 0, day(many), NOW);
    const extra = JSON.parse(JSON.stringify(original)) as NonNullable<typeof original>;
    extra.stops.push({ name: "多出来的一站", address: "", time: null, duration: 0, navigationUrl: null });
    localStorage.setItem(KEY + 7, JSON.stringify(extra));
    expect(readTodayCache(7, NOW)).toBeNull();
  });

  it("没有任何站点的今天也能缓存，只是空列表", () => {
    const source = trip();
    const cache = buildTodayCache(source, 0, day([], [], "09:00"), NOW);
    expect(cache).not.toBeNull();
    expect(cache?.stops).toEqual([]);
    expect(saveTodayCache(source, 0, day([], [], "09:00"), NOW)).not.toBeNull();
    const read = readTodayCache(7, NOW);
    expect(read).not.toBeNull();
    expect(read?.stops).toEqual([]);
    expect(read?.startDate).toBe("2026-11-07");
  });
});

describe("离线时间（README:108 缺失时显示未知）", () => {
  beforeEach(() => localStorage.clear());

  it("缺路段又缺坐标时后续站点时间留空，有高德耗时时用精确时间", () => {
    const gapDay = day([
      stop("a", "西湖", 60, ""),
      stop("b", "灵隐寺", 60, ""),
    ]);
    const gap = buildTodayCache(trip(), 0, gapDay, NOW);
    expect(gap?.stops.map(item => item.time)).toEqual(["09:00", null]);

    const routedDay = day(
      [stop("a", "西湖", 60, ""), stop("b", "灵隐寺", 60, "")],
      [route("a", "b", 600)],
    );
    const routed = buildTodayCache(trip(), 0, routedDay, NOW);
    expect(routed?.stops.map(item => item.time)).toEqual(["09:00", "10:20"]);
  });
});

describe("写入失败或数据损坏时静默降级", () => {
  beforeEach(() => localStorage.clear());

  it("没有出发日期或 dayIndex 为负时不写", () => {
    expect(buildTodayCache(trip({ startDate: null }), 0, sampleDay(), NOW)).toBeNull();
    expect(saveTodayCache(trip({ startDate: null }), 0, sampleDay(), NOW)).toBeNull();
    expect(buildTodayCache(trip(), -1, sampleDay(), NOW)).toBeNull();
    expect(localStorage.length).toBe(0);
  });

  it("退出登录清掉所有行程的今日缓存，其他键保留", () => {
    saveTodayCache(trip({ id: 7 }), 0, sampleDay(), NOW);
    saveTodayCache(trip({ id: 8 }), 0, sampleDay(), NOW);
    localStorage.setItem("unrelated", "keep");
    expect(localStorage.getItem(KEY + 7)).not.toBeNull();

    clearAllTodayCaches();
    expect(localStorage.getItem(KEY + 7)).toBeNull();
    expect(localStorage.getItem(KEY + 8)).toBeNull();
    expect(localStorage.getItem("unrelated")).toBe("keep");
  });

  it("日期被改、版本不符、结构损坏时读出 null", () => {
    saveTodayCache(trip(), 0, sampleDay(), NOW);
    const raw = localStorage.getItem(KEY + 7);
    expect(raw).not.toBeNull();
    const cache = JSON.parse(raw as string) as Record<string, unknown>;

    localStorage.setItem(KEY + 7, JSON.stringify({ ...cache, startDate: "2026-11-20" }));
    expect(readTodayCache(7, NOW)).toBeNull(); // 未来日期
    localStorage.setItem(KEY + 7, JSON.stringify({ ...cache, startDate: "2026-11-01" }));
    expect(readTodayCache(7, NOW)).toBeNull(); // 过去日期
    localStorage.setItem(KEY + 7, JSON.stringify({ ...cache, dayIndex: 5 }));
    expect(readTodayCache(7, NOW)).toBeNull(); // 与今天不符
    localStorage.setItem(KEY + 7, JSON.stringify({ ...cache, v: 2 }));
    expect(readTodayCache(7, NOW)).toBeNull();
    localStorage.setItem(KEY + 7, "{bad json");
    expect(readTodayCache(7, NOW)).toBeNull();
  });

  it("存储读取抛错时返回 null，不影响页面", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readTodayCache(7, NOW)).toBeNull();
    spy.mockRestore();
  });
});

describe("地点名缺失时写占位（README:108 缺失时显示未知）", () => {
  beforeEach(() => localStorage.clear());

  it("空名/空白名写成占位文案，写进去的快照能正常读回来", () => {
    const unnamed = day([
      { place: { id: "x", name: "", address: "", location: "", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
      { place: { id: "y", name: "   ", address: "", location: "", opentime: "", cost: "", source_time: "" }, duration: 30, reason: "" },
    ]);
    const cache = buildTodayCache(trip(), 0, unnamed, NOW);
    expect(cache).not.toBeNull();
    expect(cache?.stops.map(item => item.name)).toEqual(["地点信息暂不可用", "地点信息暂不可用"]);

    // 写读一致：normalize 不接受空名，构建时必须先把空名换成占位，否则缓存永远读不回来。
    expect(saveTodayCache(trip(), 0, unnamed, NOW)).not.toBeNull();
    const read = readTodayCache(7, NOW);
    expect(read).not.toBeNull();
    expect(read?.stops.map(item => item.name)).toEqual(["地点信息暂不可用", "地点信息暂不可用"]);
  });
});
