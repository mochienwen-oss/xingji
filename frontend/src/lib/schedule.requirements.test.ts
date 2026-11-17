import { describe, expect, it } from "vitest";
import type { Day, Place, Route, Stop } from "../types/trip";
import {
  TRANSFER_BUFFER_MINUTES,
  finishText,
  formatRange,
  formatTime,
  scheduleDay,
} from "./schedule";

/**
 * 需求出处 README.md:87：
 * 每天可以设置开始时间和希望结束时间，也可以为具体地点设置固定开始时间。
 * 页面根据停留时长和高德返回的相邻交通耗时估算时间；提前到达固定事项时计入等待，
 * 预计迟到时显示提示。缺少路段耗时时，后续时间显示待定。
 * 每日结束时间早于或等于开始时间时按次日计算；固定事项需手动选择是否在次日。
 *
 * 这里的断言按上面文案推导，换乘机动时间用实现导出的
 * TRANSFER_BUFFER_MINUTES（界面文案「含 N 分钟机动」说明它就是产品的一部分）。
 */

const START = 9 * 60; // 09:00
const TRANSIT = "transit";

function place(id: string, name: string, location = ""): Place {
  return { id, name, address: name + "地址", location, opentime: "", cost: "", source_time: "" };
}

function stop(id: string, duration: number, extra: Partial<Stop> = {}, location = ""): Stop {
  return { place: place(id, id.toUpperCase(), location), duration, reason: "", ...extra };
}

function route(origin: string, destination: string, minutes: number, mode = TRANSIT): Route {
  return { origin, destination, mode, duration: minutes * 60, polyline: [], source_time: "" };
}

function day(overrides: Partial<Day> = {}): Day {
  return { start_time: "09:00", end_time: null, stops: [], routes: [], ...overrides };
}

describe("固定开始时间（README:87 提前到达计入等待 / 迟到显示提示）", () => {
  it("提前到达固定事项时等到固定时间再开始，停留时长不被等待吃掉", () => {
    const tripDay = day({
      stops: [stop("a", 60), stop("b", 45, { fixed_time: "10:30" })],
      routes: [route("a", "b", 10)],
    });
    const result = scheduleDay(tripDay, TRANSIT);
    const arrival = START + 60 + 10 + TRANSFER_BUFFER_MINUTES; // 09:00 出发 + 1h 游览 + 10 分钟车程 + 换乘机动

    expect(result.stops[0].departure).toBe(START + 60);
    expect(result.stops[1].arrival).toBe(arrival);
    expect(result.stops[1].fixed).toBe(10 * 60 + 30);
    // 等待：到达早于固定时间，但开始时间被顶到固定时间。
    expect(result.stops[1].start).toBe(10 * 60 + 30);
    expect((result.stops[1].start as number) - (result.stops[1].arrival as number)).toBeGreaterThan(0);
    expect(result.stops[1].late).toBe(false);
    // 等待不压缩停留：45 分钟仍从固定时间起算。
    expect(result.stops[1].departure).toBe(10 * 60 + 30 + 45);
    expect(result.finish).toBe(10 * 60 + 30 + 45);
    expect(formatRange(result.stops[1].start, result.stops[1].departure)).toBe("10:30–11:15");
  });

  it("预计迟到时给出提示，且时间不会被倒拨到固定时间", () => {
    const tripDay = day({
      stops: [stop("a", 60), stop("b", 45, { fixed_time: "10:10" })],
      routes: [route("a", "b", 10)],
    });
    const result = scheduleDay(tripDay, TRANSIT);
    const arrival = START + 60 + 10 + TRANSFER_BUFFER_MINUTES; // 10:20，晚于 10:10

    expect(result.stops[1].arrival).toBe(arrival);
    expect(result.stops[1].late).toBe(true);
    // 已经迟到时仍按真实到达时间开始，不能假装 10:10 就到了。
    expect(result.stops[1].start).toBe(arrival);
    expect(result.stops[1].start as number).toBeGreaterThanOrEqual(10 * 60 + 10);
    expect(result.stops[1].departure).toBe(arrival + 45);
  });

  it("固定事项是否在次日由数据手动决定，不能自动滚动", () => {
    const sameDay = scheduleDay(
      day({ stops: [stop("a", 60, { fixed_time: "08:00", fixed_next_day: false })] }),
      TRANSIT,
    );
    expect(sameDay.stops[0].fixed).toBe(8 * 60);
    expect(sameDay.stops[0].late).toBe(true); // 09:00 才出发，当天 08:00 已经错过

    const nextDay = scheduleDay(
      day({ stops: [stop("a", 60, { fixed_time: "08:00", fixed_next_day: true })] }),
      TRANSIT,
    );
    expect(nextDay.stops[0].fixed).toBe(8 * 60 + 1440);
    expect(nextDay.stops[0].late).toBe(false);
    expect(nextDay.stops[0].start).toBe(8 * 60 + 1440);
    expect(nextDay.stops[0].departure).toBe(8 * 60 + 1440 + 60);
    expect(formatTime(nextDay.finish as number)).toBe("次日 09:00");
  });

  it("固定时间正好等于到达时间时既不算迟到也不产生等待", () => {
    const arrival = START + 60 + 10 + TRANSFER_BUFFER_MINUTES; // 10:20
    const result = scheduleDay(
      day({
        stops: [stop("a", 60), stop("b", 30, { fixed_time: "10:20" })],
        routes: [route("a", "b", 10)],
      }),
      TRANSIT,
    );
    expect(result.stops[1].arrival).toBe(arrival);
    expect(result.stops[1].start).toBe(arrival);
    expect(result.stops[1].late).toBe(false);
  });
});

describe("每日结束时间（README:87 早于或等于开始时间按次日计算）", () => {
  it("结束时间早于开始时间时截止时间落到次日", () => {
    const result = scheduleDay(day({ end_time: "08:00", stops: [stop("a", 60)] }), TRANSIT);
    expect(result.deadline).toBe(8 * 60 + 1440);
    expect(formatTime(result.deadline as number)).toBe("次日 08:00");
    expect(result.finish).toBe(START + 60);
    // 10:00 结束仍在次日 08:00 之前，不该提示晚于。
    expect(finishText(result.finish, result.deadline)).toBe("预计 10:00 结束");
  });

  it("结束时间等于开始时间时同样按次日", () => {
    const result = scheduleDay(day({ end_time: "09:00", stops: [stop("a", 60)] }), TRANSIT);
    expect(result.deadline).toBe(START + 1440);
    expect(formatTime(result.deadline as number)).toBe("次日 09:00");
  });

  it("没有设置结束时间时不做截止判断", () => {
    const result = scheduleDay(day({ end_time: null, stops: [stop("a", 60)] }), TRANSIT);
    expect(result.deadline).toBeNull();
    expect(finishText(result.finish, result.deadline)).toBe("预计 10:00 结束");
  });

  it("超过截止时间时文案里报出晚于几点", () => {
    const result = scheduleDay(
      day({
        end_time: "10:00",
        stops: [stop("a", 90), stop("b", 60)],
        routes: [route("a", "b", 15)],
      }),
      TRANSIT,
    );
    expect(result.deadline).toBe(10 * 60);
    expect(result.finish).toBe(START + 90 + 15 + TRANSFER_BUFFER_MINUTES + 60);
    expect(finishText(result.finish, result.deadline)).toBe("预计 11:55 结束，晚于 10:00");
  });
});

describe("相邻交通耗时只认与本天匹配的高德路段（README:87 依据相邻交通耗时）", () => {
  const stops = [stop("a", 60, {}, "120.15,30.28"), stop("b", 60, {}, "120.20,30.28")];
  const exactArrival = START + 60 + 10 + TRANSFER_BUFFER_MINUTES; // 精确路段 10 分钟 → 10:20

  it("交通方式不一致的路段不能当作精确耗时", () => {
    const result = scheduleDay(day({ stops, routes: [route("a", "b", 10, "driving")] }), "transit");
    // 不是本天的交通方式：不能采用这段耗时，也不能拿坐标猜。
    expect(result.stops[1].start).not.toBe(exactArrival);
    expect(result.stops[1].start).toBeNull();
    expect(result.incomplete).toBe(true);
  });

  it("起点终点对不上的路段不能当作精确耗时（换序或重新排序后的旧数据）", () => {
    const swapped = scheduleDay(day({ stops, routes: [route("b", "a", 10)] }), "transit");
    expect(swapped.stops[1].start).not.toBe(exactArrival);
    expect(swapped.stops[1].start).toBeNull();
    expect(swapped.incomplete).toBe(true);

    const stale = scheduleDay(
      day({ stops, routes: [route("unrelated", "also-unrelated", 10)] }),
      "transit",
    );
    expect(stale.stops[1].start).not.toBe(exactArrival);
    expect(stale.stops[1].start).toBeNull();
    expect(stale.incomplete).toBe(true);
  });

  it("高德没返回耗时（duration 为 null）时同样不能当精确耗时", () => {
    const nullDuration: Route = { ...route("a", "b", 10), duration: null };
    const result = scheduleDay(day({ stops, routes: [nullDuration] }), "transit");
    expect(result.stops[1].start).not.toBe(exactArrival);
    expect(result.stops[1].start).toBeNull();
    expect(result.incomplete).toBe(true);
  });
});

describe("缺少路段耗时（README:87 后续时间显示待定 / README:108 缺失时显示未知）", () => {
  it("既没有路段也没有坐标时，后续站点全部待定", () => {
    const result = scheduleDay(
      day({ stops: [stop("a", 60), stop("b", 60), stop("c", 60)] }),
      TRANSIT,
    );
    expect(result.stops[0].start).toBe(START);
    expect(result.stops[0].departure).toBe(START + 60);
    expect(result.stops[1].arrival).toBeNull();
    expect(result.stops[1].start).toBeNull();
    expect(result.stops[2].arrival).toBeNull();
    expect(result.stops[2].start).toBeNull();
    expect(result.incomplete).toBe(true);
    expect(result.finish).toBeNull();
  });

  it("有坐标但缺路线时也显示待定，不拿直线距离估算", () => {
    const result = scheduleDay(
      day({ stops: [stop("a", 60, {}, "120.15,30.28"), stop("b", 60, {}, "120.20,30.28")] }),
      TRANSIT,
    );
    expect(result.stops[1].start).toBeNull();
    expect(result.stops[1].departure).toBeNull();
    expect(result.incomplete).toBe(true);
    expect(result.finish).toBeNull();
    // 没有精确路段就不存在换乘机动，不能把缓冲算进去。
    expect(result.buffer).toBe(0);
  });

  it("中间一段缺路段且缺坐标后，后面的路段即使有数据也不再推算", () => {
    const result = scheduleDay(
      day({
        stops: [stop("a", 60, {}, "120.15,30.28"), stop("b", 60, {}), stop("c", 60, {}, "120.30,30.28")],
        routes: [route("b", "c", 10)], // 只有 b→c 有高德耗时；a→b 缺失后，后续路段也不再推算
      }),
      TRANSIT,
    );
    expect(result.stops[1].start).toBeNull();
    expect(result.stops[2].start).toBeNull();
    expect(result.finish).toBeNull();
  });

  it("后续站点即使有固定时间也不会在待定状态上硬凑时间", () => {
    const result = scheduleDay(
      day({
        stops: [stop("a", 60, {}, "120.15,30.28"), stop("b", 60, {}), stop("c", 30, { fixed_time: "15:00" })],
        routes: [route("b", "c", 10)], // a→b 缺耗时，后面的固定时间也只能待定
      }),
      TRANSIT,
    );
    expect(result.stops[2].start).toBeNull();
    expect(result.stops[2].late).toBe(false);
    expect(result.incomplete).toBe(true);
  });
});

describe("停留时长（README:87 页面根据停留时长估算；缺失时显示未知）", () => {
  it("停留时长不合法（小于 15、大于 480、非整数）时该站结束时间与后续时间都待定", () => {
    for (const duration of [10, 14, 481, 600, 60.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      const result = scheduleDay(
        day({
          stops: [stop("a", duration, {}, "120.15,30.28"), stop("b", 60, {}, "120.20,30.28")],
          routes: [route("a", "b", 10)],
        }),
        TRANSIT,
      );
      expect(result.stops[0].start).toBe(START);
      expect(result.stops[0].departure).toBeNull();
      expect(result.stops[1].start).toBeNull();
      expect(result.incomplete).toBe(true);
      expect(result.finish).toBeNull();
    }
  });

  it("15 与 480 分钟是合法边界", () => {
    expect(scheduleDay(day({ stops: [stop("a", 15)] }), TRANSIT).stops[0].departure).toBe(START + 15);
    expect(scheduleDay(day({ stops: [stop("a", 480)] }), TRANSIT).stops[0].departure).toBe(START + 480);
  });
});

describe("一天的时间只由停留时长与相邻交通构成", () => {
  it("三站各停留 60 分钟、两段各 10 分钟车程：结束时间是两者之和加换乘机动", () => {
    const result = scheduleDay(
      day({
        stops: [stop("a", 60), stop("b", 60), stop("c", 60)],
        routes: [route("a", "b", 10), route("b", "c", 10)],
      }),
      TRANSIT,
    );
    const expectedFinish = START + 60 * 3 + (10 + TRANSFER_BUFFER_MINUTES) * 2;
    expect(result.finish).toBe(expectedFinish);
    expect(result.buffer).toBe(TRANSFER_BUFFER_MINUTES * 2);
    // 换乘机动在界面文案里明说，避免用户把缓冲当成真实游玩时长。
    expect(finishText(result.finish, 18 * 60, result.buffer)).toBe(
      "预计 12:40 结束（含 " + TRANSFER_BUFFER_MINUTES * 2 + " 分钟机动）",
    );
  });

  it("没有开始时间或没有站点时不臆造时间", () => {
    const noStart = scheduleDay(
      day({ start_time: null, stops: [stop("a", 60, { fixed_time: "10:00" })] }),
      TRANSIT,
    );
    expect(noStart.stops).toHaveLength(0);
    expect(noStart.finish).toBeNull();
    expect(noStart.incomplete).toBe(false);

    const empty = scheduleDay(day({ stops: [] }), TRANSIT);
    expect(empty.stops).toHaveLength(0);
    expect(empty.finish).toBeNull();
    expect(empty.incomplete).toBe(false);
  });
});

describe("时间字段解析（非法值按未知处理，不产生 NaN）", () => {
  it("开始时间非法时按未设置处理，不排任何时间", () => {
    for (const bad of ["abc", "9:00", "24:00", "09:60", "09:00:00", " "]) {
      const result = scheduleDay(day({ start_time: bad, stops: [stop("a", 60)] }), TRANSIT);
      expect(result.stops).toEqual([]);
      expect(result.finish).toBeNull();
      expect(result.deadline).toBeNull();
      expect(result.incomplete).toBe(false);
    }
  });

  it("结束时间非法时不做截止判断，站点时间仍按停留算", () => {
    const result = scheduleDay(day({ end_time: "25:00", stops: [stop("a", 60)] }), TRANSIT);
    expect(result.deadline).toBeNull();
    expect(result.stops[0].start).toBe(START);
    expect(result.stops[0].departure).toBe(START + 60);
    expect(Number.isNaN(result.finish as number)).toBe(false);
  });

  it("固定时间非法时按没有固定时间处理", () => {
    const result = scheduleDay(day({ stops: [stop("a", 60, { fixed_time: "8:00" })] }), TRANSIT);
    expect(result.stops[0].fixed).toBeNull();
    expect(result.stops[0].late).toBe(false);
    expect(result.stops[0].start).toBe(START);
  });

  it("合法的 HH:MM 边界值仍能解析（00:00 与 23:59）", () => {
    const midnight = scheduleDay(day({ start_time: "00:00", stops: [stop("a", 15)] }), TRANSIT);
    expect(midnight.stops[0].start).toBe(0);
    expect(midnight.stops[0].departure).toBe(15);
    expect(scheduleDay(day({ end_time: "23:59", stops: [stop("a", 15)] }), TRANSIT).deadline).toBe(1439);
  });
});

describe("时间文案（跨日显示）", () => {
  it("当天、次日与更晚用不同前缀表达", () => {
    expect(formatTime(0)).toBe("00:00");
    expect(formatTime(1439)).toBe("23:59");
    expect(formatTime(1440)).toBe("次日 00:00");
    expect(formatTime(1500)).toBe("次日 01:00");
    expect(formatTime(2879)).toBe("次日 23:59");
    expect(formatTime(2880)).toBe("+2天 00:00");
  });

  it("一段时间的任一端未知时整段显示不了", () => {
    expect(formatRange(null, 600)).toBeNull();
    expect(formatRange(600, null)).toBeNull();
    expect(formatRange(null, null)).toBeNull();
    expect(formatRange(23 * 60 + 30, 24 * 60 + 30)).toBe("23:30–次日 00:30");
  });

  it("结束文案在跨日与未知时都不说谎", () => {
    expect(finishText(24 * 60 + 30, 18 * 60)).toBe("预计 次日 00:30 结束，晚于 18:00");
    expect(finishText(24 * 60 + 30, 18 * 60, 20)).toBe(
      "预计 次日 00:30 结束（含 20 分钟机动），晚于 18:00",
    );
    expect(finishText(null, 18 * 60)).toBeNull();
  });
});
