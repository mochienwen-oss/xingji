import { describe, expect, it } from "vitest";
import type { Day } from "../types/trip";
import { finishText, formatRange, scheduleDay } from "./schedule";

const day: Day = {
  start_time: "09:00",
  stops: [
    { place: { id: "a", name: "A", address: "", location: "", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
    { place: { id: "b", name: "B", address: "", location: "", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
  ],
  routes: [
    {
      origin: "a",
      destination: "b",
      mode: "transit",
      duration: 600,
      polyline: [],
      source_time: "",
    },
  ],
};

describe("scheduleDay", () => {
  it("turns a start time and routes into concrete stop ranges", () => {
    const result = scheduleDay(day, "transit");
    expect(result.stops[0].start).toBe(9 * 60);
    expect(result.stops[0].departure).toBe(10 * 60);
    expect(result.stops[1].start).toBe(10 * 60 + 20);
    expect(result.stops[1].departure).toBe(11 * 60 + 20);
    expect(formatRange(result.stops[1].start, result.stops[1].departure)).toBe("10:20–11:20");
    expect(result.finish).toBe(11 * 60 + 20);
    expect(result.buffer).toBe(10);
  });

  it("leaves the rest pending when a leg has no route", () => {
    // 有坐标但没有高德路段时也不能估算：需求要求后续时间显示待定。
    const guessed: Day = {
      start_time: "09:00",
      stops: [
        { place: { id: "a", name: "A", address: "", location: "120.15,30.28", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
        { place: { id: "b", name: "B", address: "", location: "120.17,30.28", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
      ],
      routes: [],
    };
    const result = scheduleDay(guessed, "walking");
    expect(result.stops[1].arrival).toBeNull();
    expect(result.stops[1].start).toBeNull();
    expect(result.stops[1].departure).toBeNull();
    expect(result.incomplete).toBe(true);
    expect(result.finish).toBeNull();
  });

  it("stays incomplete when neither a route nor coordinates exist", () => {
    const bare: Day = {
      start_time: "09:00",
      stops: [
        { place: { id: "a", name: "A", address: "", location: "", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
        { place: { id: "b", name: "B", address: "", location: "", opentime: "", cost: "", source_time: "" }, duration: 60, reason: "" },
      ],
      routes: [],
    };
    const result = scheduleDay(bare, "transit");
    expect(result.incomplete).toBe(true);
    expect(result.finish).toBeNull();
  });

  it("marks the range as next-day when it crosses midnight", () => {
    expect(formatRange(23 * 60 + 30, 24 * 60 + 30)).toBe("23:30–次日 00:30");
    expect(formatRange(null, 600)).toBeNull();
  });
});
describe("finishText", () => {
  it("states the estimated finish and flags a late end", () => {
    expect(finishText(17 * 60 + 10, 18 * 60)).toBe("预计 17:10 结束");
    expect(finishText(18 * 60 + 40, 18 * 60)).toBe("预计 18:40 结束，晚于 18:00");
    expect(finishText(17 * 60 + 10, 18 * 60, 20)).toBe("预计 17:10 结束（含 20 分钟机动）");
    expect(finishText(18 * 60 + 40, 18 * 60, 10)).toBe("预计 18:40 结束（含 10 分钟机动），晚于 18:00");
  });

  it("returns nothing when the finish is unknown", () => {
    expect(finishText(null, 18 * 60)).toBeNull();
  });
});
