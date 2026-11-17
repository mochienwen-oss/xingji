import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Day, Stop } from "../../types/trip";
import { Timeline } from "./Timeline";

/**
 * 需求出处 README.md:87：「固定事项需手动选择是否在次日」。
 * 时间线在拿不到完整排程（当天没设开始时间、或前一段缺路线）时，
 * 仍要把固定时刻显示出来，并且不能丢掉「次日」标记。
 */

function makeStop(id: string, overrides: Partial<Stop> = {}): Stop {
  return {
    place: {
      id,
      name: `地点${id}`,
      address: "",
      location: "120.15,30.25",
      opentime: "",
      cost: "",
      source_time: "",
    },
    duration: 60,
    reason: "",
    ...overrides,
  };
}

function renderTimeline(day: Day, scheduled: { arrival: number | null; start: number | null; departure: number | null; fixed: number | null; late: boolean }[] = []) {
  render(
    <Timeline
      day={day}
      dayIndex={0}
      transport="transit"
      dirty={false}
      busy={false}
      routeBusy={false}
      backlogCount={0}
      scheduled={scheduled}
      onOpenStop={() => {}}
      onReorder={() => {}}
      onRecomputeRoutes={() => {}}
      onOpenBacklog={() => {}}
      onOpenNearby={() => {}}
    />,
  );
}

describe("Timeline 站点时间展示（README:87 固定次日）", () => {
  it("没有排程时仍显示固定时间，次日标记不能丢", () => {
    // 当天没设开始时间 → scheduleDay 返回空排程；固定 00:30 在次日。
    renderTimeline({
      stops: [makeStop("a", { fixed_time: "00:30", fixed_next_day: true })],
      routes: [],
      start_time: null,
      end_time: null,
    });
    expect(screen.getByText("次日 00:30")).toBeInTheDocument();
  });

  it("没有排程也没有固定时间时显示待定", () => {
    renderTimeline({ stops: [makeStop("a")], routes: [], start_time: null });
    expect(screen.getByText("待定")).toBeInTheDocument();
  });

  it("有排程时按排程时间显示，不再回退固定时间", () => {
    renderTimeline(
      { stops: [makeStop("a", { fixed_time: "00:30", fixed_next_day: true })], routes: [], start_time: "09:00" },
      [{ arrival: 540, start: 540, departure: 600, fixed: 1470, late: false }],
    );
    expect(screen.getByText("09:00–10:00")).toBeInTheDocument();
  });
});
