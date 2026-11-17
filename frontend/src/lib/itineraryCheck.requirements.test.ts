import { describe, expect, it } from "vitest";
import type { Day, Place, Stop } from "../types/trip";
import {
  healthCopy,
  parseOpenDays,
  runItineraryChecks,
  startDateForDay,
  weekdayMon,
} from "./itineraryCheck";

/**
 * 需求出处：README.md:87「页面根据停留时长…每日结束时间…」、README.md:85
 * 与体检 v1 需求：
 * - 有出发日期时核对当天是否命中地点固定的闭馆日；
 * - 没有出发日期时只按固定闭馆日聚合提示，不猜具体哪一天；
 * - 单日 ≥7 站或停留 ≥600 分钟视为偏满；
 * - 同一天相邻两站直线距离 ≥30km 视为较远路程；
 * - 同一地点重复出现；
 * - 解析不了开放时间的宁可少提示，也不误报。
 * UI 文案见 frontend/src/components/trip/TripHealth.tsx 与 healthCopy。
 */

function place(
  id: string,
  opts: {
    name?: string;
    location?: string;
    opentime?: string;
    unavailable?: boolean;
    verification?: Place["verification"];
  } = {},
): Place {
  return {
    id,
    name: opts.name ?? id,
    address: "",
    location: opts.location ?? "",
    opentime: opts.opentime ?? "",
    cost: "",
    source_time: "",
    ...(opts.unavailable === undefined ? {} : { unavailable: opts.unavailable }),
    ...(opts.verification === undefined ? {} : { verification: opts.verification }),
  };
}

function stop(id: string, duration = 0, opts: Parameters<typeof place>[1] = {}): Stop {
  return { place: place(id, opts), duration, reason: "" };
}

function day(...stops: Stop[]): Day {
  return { stops, routes: [] };
}

function codes(checks: ReturnType<typeof runItineraryChecks>): string[] {
  return checks.map(check => check.code);
}

describe("出发日期决定闭馆判断（README:87 选定日期后核对）", () => {
  it("有出发日期时只按当天星期判断，并逐天分别提示", () => {
    const checks = runItineraryChecks({
      days: [
        // 2026-11-09 是周一
        day(
          stop("a", 0, { name: "周一闭馆馆", opentime: "周二至周日 09:00-17:00" }),
          stop("b", 0, { name: "每天开放馆", opentime: "周一至周日 09:00-17:00" }),
        ),
        // 第二天周二
        day(stop("c", 0, { name: "周二闭馆馆", opentime: "周一、周三 09:00-17:00" })),
      ],
      request: { start_date: "2026-11-09" },
    });
    expect(codes(checks)).toEqual(["closed_day", "closed_day"]);
    expect(checks[0]).toMatchObject({ day: 1, place: "周一闭馆馆", weekday: 1, severity: "warning" });
    expect(checks[1]).toMatchObject({ day: 2, place: "周二闭馆馆", weekday: 2 });
  });

  it("选定出发日期后不再重复输出固定闭馆日聚合", () => {
    const checks = runItineraryChecks({
      days: [day(stop("a", 0, { name: "周一闭馆馆", opentime: "周二至周日 09:00-17:00" }), stop("b", 0))],
      request: { start_date: "2026-11-09" },
    });
    expect(codes(checks)).not.toContain("weekly_closure");
  });
});

describe("没有可用出发日期时按固定闭馆日聚合（README:87 未选日期先提示）", () => {
  it("不猜具体哪一天，只把每个地点的闭馆星期汇总出来", () => {
    const checks = runItineraryChecks({
      days: [
        day(stop("a", 0, { name: "周一闭馆馆", opentime: "周二至周日 09:00-17:00" })),
        day(stop("b", 0, { name: "周四闭馆馆", opentime: "周一、周四 09:00-17:00" })),
      ],
      request: { start_date: null },
    });
    expect(codes(checks)).toEqual(["weekly_closure"]);
    const weekly = checks[0];
    if (weekly.code !== "weekly_closure") throw new Error("expected weekly_closure");
    expect(weekly.severity).toBe("info");
    expect(weekly.places).toEqual([
      { name: "周一闭馆馆", closedDays: [1] },
      { name: "周四闭馆馆", closedDays: [2, 3, 5, 6, 7] },
    ]);
  });

  it("同一地点排在不同天时只聚合一条，闭馆星期取并集", () => {
    const checks = runItineraryChecks({
      days: [
        day(stop("museum", 0, { name: "博物馆", opentime: "周二至周日 09:00-17:00" })),
        day(stop("museum", 0, { name: "博物馆", opentime: "周二至周日 09:00-17:00" })),
      ],
      backlog: [],
      request: null,
    });
    const weekly = checks.find(check => check.code === "weekly_closure");
    expect(weekly).toBeTruthy();
    if (weekly?.code !== "weekly_closure") throw new Error("expected weekly_closure");
    expect(weekly.places).toHaveLength(1);
    expect(weekly.places[0]).toEqual({ name: "博物馆", closedDays: [1] });
    // 同一地点重复安排本身也是要提示的，但不应污染聚合结果。
    const duplicate = checks.find(check => check.code === "duplicate_place");
    expect(duplicate).toMatchObject({ code: "duplicate_place", name: "博物馆", count: 2 });
  });

  it("出发日期写了但解析不了时，固定闭馆日仍然提示，不能静默丢失", () => {
    const unparseable = runItineraryChecks({
      days: [day(stop("a", 0, { name: "周一闭馆馆", opentime: "周二至周日 09:00-17:00" }))],
      request: { start_date: "待定" },
    });
    expect(codes(unparseable)).toEqual(["weekly_closure"]);

    // 日历上不存在的日期同样不能当成有效日期，也不能因此丢掉闭馆提示。
    const invalidCalendar = runItineraryChecks({
      days: [day(stop("a", 0, { name: "周一闭馆馆", opentime: "周二至周日 09:00-17:00" }))],
      request: { start_date: "2026-02-30" },
    });
    expect(codes(invalidCalendar)).toEqual(["weekly_closure"]);
  });
});

describe("单日强度（README:87 一天排得太满要提醒，阈值见 docs:127）", () => {
  it("6 站停留 599.4 分钟还不算偏满", () => {
    const stops = Array.from({ length: 6 }, (_, index) => stop("s" + index, 99.9));
    expect(codes(runItineraryChecks({ days: [day(...stops)] }))).not.toContain("heavy_day");
  });

  it("停留时间达到 600 分钟即提示，并报出站点数与分钟数", () => {
    const stops = Array.from({ length: 6 }, (_, index) => stop("s" + index, 100));
    const checks = runItineraryChecks({ days: [day(...stops)] });
    expect(checks).toEqual([{ code: "heavy_day", severity: "warning", day: 1, stops: 6, minutes: 600 }]);
  });

  it("站数达到 7 时即使停留时间很短也提示", () => {
    const stops = Array.from({ length: 7 }, (_, index) => stop("s" + index, 0));
    const checks = runItineraryChecks({ days: [day(...stops)] });
    expect(checks).toEqual([{ code: "heavy_day", severity: "warning", day: 1, stops: 7, minutes: 0 }]);
  });
});

describe("相邻地点距离（docs:127 直线 ≥30km 视为较远）", () => {
  it("29.99 公里不提示，30.02 公里提示", () => {
    const near = runItineraryChecks({
      days: [day(stop("a", 0, { location: "120.150000,30.280000" }), stop("b", 0, { location: "120.150000,30.549700" }))],
    });
    expect(codes(near)).not.toContain("long_hop");

    const far = runItineraryChecks({
      days: [day(stop("a", 0, { location: "120.150000,30.280000" }), stop("b", 0, { location: "120.150000,30.550000" }))],
    });
    expect(codes(far)).toEqual(["long_hop"]);
    expect(far[0]).toMatchObject({ code: "long_hop", severity: "warning", day: 1, from: "a", to: "b", km: 30 });
  });

  it("一天有多段较远路程时只报最远一段", () => {
    const checks = runItineraryChecks({
      days: [
        day(
          stop("a", 0, { name: "A", location: "120.150000,30.000000" }),
          stop("b", 0, { name: "B", location: "120.150000,30.270000" }),
          stop("c", 0, { name: "C", location: "120.150000,30.670000" }),
        ),
      ],
    });
    const hops = checks.filter(check => check.code === "long_hop");
    expect(hops).toEqual([{ code: "long_hop", severity: "warning", day: 1, from: "B", to: "C", km: 44.5 }]);
  });

  it("坐标缺失或不是数字时跳过该段，不拿直线乱报", () => {
    const checks = runItineraryChecks({
      days: [
        day(
          stop("a", 0, { location: "" }),
          stop("b", 0, { location: "abc" }),
          stop("c", 0, { location: "120.15,30.55" }),
        ),
      ],
    });
    expect(codes(checks)).not.toContain("long_hop");
  });
});

describe("同一地点重复安排（docs:127 duplicate_place）", () => {
  it("跨天与候选清单一起计数", () => {
    const checks = runItineraryChecks({
      days: [day(stop("westlake", 0, { name: "西湖" })), day(stop("westlake", 0, { name: "西湖" }))],
      backlog: [stop("westlake", 0, { name: "西湖" })],
    });
    expect(checks).toEqual([{ code: "duplicate_place", severity: "info", name: "西湖", count: 3 }]);
  });

  it("同名但不是同一地点、或只出现一次时不提示", () => {
    const checks = runItineraryChecks({
      days: [day(stop("a", 0, { name: "西湖" }), stop("b", 0, { name: "西湖" }), stop("c", 0, { name: "灵隐寺" }))],
    });
    expect(codes(checks)).not.toContain("duplicate_place");
  });
});

describe("宁可少提示也不误报（README:85 校验不能覆盖所有情况）", () => {
  it("开放时间解析不了、未复核或标注不可用时不提示", () => {
    const checks = runItineraryChecks({
      days: [
        day(
          stop("a", 0, { name: "只写闭馆", opentime: "周一闭馆" }),
          stop("b", 0, {
            name: "未复核",
            opentime: "周一 09:00-17:00",
            verification: { status: "needs_check", source: "amap", checked_at: "2026-11-01", opening_hours: false },
          }),
          stop("c", 0, { name: "不可用", opentime: "周二 09:00-17:00", unavailable: true }),
          stop("d", 0, { name: "没有开放时间", opentime: "" }),
        ),
      ],
      request: { start_date: "2026-11-09" },
    });
    expect(checks).toEqual([]);
  });

});

describe("提示排序（README:87 先报必须处理的，再报提醒）", () => {
  it("warning 排在 info 前，day 相同时按代码排序", () => {
    const placeMondayClosed = stop("museum", 0, { name: "博物馆", opentime: "周一 09:00-17:00" });
    const checks = runItineraryChecks({
      days: [
        day(placeMondayClosed, stop("b", 0), stop("c", 0), stop("d", 0), stop("e", 0), stop("f", 0), stop("g", 0)),
        day(placeMondayClosed),
      ],
      request: null,
    });
    expect(codes(checks)).toEqual(["heavy_day", "duplicate_place", "weekly_closure"]);
  });

  it("多条 warning 先按天再按代码排序", () => {
    const checks = runItineraryChecks({
      days: [
        // 周一（2026-11-09）闭馆 + 7 站偏满
        day(
          stop("a", 0, { name: "周一闭馆馆", opentime: "周二 09:00-17:00" }),
          stop("b", 0),
          stop("c", 0),
          stop("d", 0),
          stop("e", 0),
          stop("f", 0),
          stop("g", 0),
        ),
        // 周二闭馆
        day(stop("h", 0, { name: "周二闭馆馆", opentime: "周一 09:00-17:00" })),
      ],
      request: { start_date: "2026-11-09" },
    });
    expect(checks.map(check => [check.code, "day" in check ? check.day : 99])).toEqual([
      ["closed_day", 1],
      ["heavy_day", 1],
      ["closed_day", 2],
    ]);
  });
});

describe("输入健壮性", () => {
  it("空行程、空天、缺 request/backlog 都返回空列表", () => {
    expect(runItineraryChecks({ days: [] })).toEqual([]);
    expect(runItineraryChecks({ days: [day()] })).toEqual([]);
    expect(runItineraryChecks({ days: [day()], request: null, backlog: null })).toEqual([]);
    expect(runItineraryChecks({ days: null as unknown as Day[], backlog: null })).toEqual([]);
  });
});

describe("出发日期换算", () => {
  it("按本地日期加天，跨月跨年正确，只取日期部分", () => {
    const newYear = startDateForDay("2026-12-31", 1);
    expect(newYear).not.toBeNull();
    expect(newYear?.getFullYear()).toBe(2027);
    expect(newYear?.getMonth()).toBe(0);
    expect(newYear?.getDate()).toBe(1);
    expect(weekdayMon(newYear as Date)).toBe(5); // 2027-01-01 周五

    const withTime = startDateForDay("2026-11-09T08:30:00Z", 0);
    expect(withTime?.getFullYear()).toBe(2026);
    expect(withTime?.getMonth()).toBe(10);
    expect(withTime?.getDate()).toBe(9);
  });

  it("没有日期或格式无法识别时返回 null", () => {
    expect(startDateForDay(null, 0)).toBeNull();
    expect(startDateForDay(undefined, 0)).toBeNull();
    expect(startDateForDay("", 0)).toBeNull();
    expect(startDateForDay("待定", 2)).toBeNull();
    expect(startDateForDay("11/09/2026", 0)).toBeNull();
  });

  it("日历上不存在的日期返回 null，而不是被 Date 顺延", () => {
    expect(startDateForDay("2026-02-30", 0)).toBeNull();
    expect(startDateForDay("2026-02-29", 0)).toBeNull(); // 2026 不是闰年
    expect(startDateForDay("2026-04-31", 0)).toBeNull();
    expect(startDateForDay("2026-13-01", 0)).toBeNull();
    expect(startDateForDay("2026-00-10", 0)).toBeNull();
    // 闰年 2 月 29 日是合法日期。
    const leap = startDateForDay("2028-02-29", 0);
    expect(leap?.getFullYear()).toBe(2028);
    expect(leap?.getMonth()).toBe(1);
    expect(leap?.getDate()).toBe(29);
  });

  it("周一=1、周日=7", () => {
    expect(weekdayMon(new Date(2026, 10, 8))).toBe(7); // 周日
    expect(weekdayMon(new Date(2026, 10, 9))).toBe(1); // 周一
    expect(weekdayMon(new Date(2026, 10, 7))).toBe(6); // 周六
  });
});

describe("开放时间解析（parseOpenDays）", () => {
  it("识别中文星期、跨周区间与全角破折号", () => {
    expect([...(parseOpenDays("周五至周一 09:00-17:00") ?? [])]).toEqual([1, 5, 6, 7]);
    expect([...(parseOpenDays("星期一 09:00-17:00") ?? [])]).toEqual([1]);
    expect([...(parseOpenDays("周六至周一 09:00–17:00") ?? [])]).toEqual([1, 6, 7]);
    expect([...(parseOpenDays("周一至周日 09:00-17:00") ?? [])]).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("先记营业时段再扣掉闭馆日，闭馆说明优先", () => {
    expect([...(parseOpenDays("周一 全天关闭；周一至周日 09:00-17:00") ?? [])]).toEqual([2, 3, 4, 5, 6, 7]);
    expect([...(parseOpenDays("全年 周一 09:00-17:00；周二 闭馆") ?? [])]).toEqual([1]);
    expect([...(parseOpenDays("周一、周三 09:00-17:00；周四 休息") ?? [])]).toEqual([1, 3]);
  });

  it("没有明确星期+时段、或只有写到店时间时返回 null，宁可不提示", () => {
    expect(parseOpenDays("")).toBeNull();
    expect(parseOpenDays("周一闭馆")).toBeNull();
    expect(parseOpenDays("周一")).toBeNull();
    expect(parseOpenDays("09:00-17:00")).toBeNull();
  });

  it("全天开放的写法覆盖整周", () => {
    expect([...(parseOpenDays("全天开放") ?? [])]).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect([...(parseOpenDays("24小时开放") ?? [])]).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });
});

describe("体检文案（TripHealth 展示，healthCopy）", () => {
  it("中文文案把地点、星期、天数、距离带进句子里", () => {
    const zh = healthCopy("zh");
    expect(zh.closedDayTitle(2)).toBe("第 2 天可能闭馆");
    expect(zh.closedDayDetail("西湖", zh.weekday(1))).toBe("西湖 在周一闭馆，建议调整日期或替换地点。");
    expect(zh.weekday(7)).toBe("周日");
    expect(zh.weeklyTitle(2)).toBe("2 个地点有固定闭馆日");
    expect(zh.weeklyItem("西湖", "周一、周二")).toBe("西湖 · 周一、周二闭馆");
    expect(zh.weeklyDetail(["西湖", "灵隐寺"], 1)).toBe("西湖、灵隐寺 等 1 个；选定出发日期后会自动核对。");
    expect(zh.longHopDetail("A", "B", "44.5")).toBe("A → B 直线约 44.5 公里，建议确认交通方式与时间。");
    expect(zh.heavyDetail(6, "10")).toBe("共 6 个地点，停留约 10 小时，建议留出机动和用餐时间。");
    expect(zh.duplicateDetail("西湖", 3)).toBe("西湖 在行程中出现 3 次，确认是否需要合并。");
  });

  it("英文文案与数量单复数正确，默认语言是中文", () => {
    const en = healthCopy("en");
    expect(en.count(1)).toBe("1 check");
    expect(en.count(2)).toBe("2 checks");
    expect(en.closedDayDetail("West Lake", en.weekday(1))).toBe(
      "West Lake is closed on Monday. Adjust the date or swap the stop.",
    );
    expect(en.heavyTitle(2)).toBe("Day 2 is packed");
    expect(healthCopy().sectionTitle).toBe("行程体检");
    expect(healthCopy().count(3)).toBe("3 项建议");
  });
});
