import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Day, Place, Stop } from "../../types/trip";
import { TripHealth } from "./TripHealth";

function place(overrides: Partial<Place> = {}): Place {
  return {
    id: "p1",
    name: "杭州博物馆",
    address: "",
    location: "120.166525,30.239091",
    opentime: "全年 周一, 周三–周日 09:00–16:30",
    cost: "",
    source_time: "",
    verification: { status: "verified", source: "amap", checked_at: "2026-11-07T00:00:00Z", opening_hours: true },
    ...overrides,
  };
}

function stop(): Stop {
  return { place: place(), duration: 60, reason: "" };
}

function day(stops: Stop[]): Day {
  return { stops, routes: [] };
}

describe("TripHealth", () => {
  it("shows fixed closing days when the trip has no start date", () => {
    render(<TripHealth days={[day([stop()])]} request={{ start_date: null }} />);
    expect(screen.getByText("行程体检")).toBeInTheDocument();
    expect(screen.getByText("1 个地点有固定闭馆日")).toBeInTheDocument();
    expect(screen.getByText(/杭州博物馆 · 周二闭馆/)).toBeInTheDocument();
  });

  it("warns when the start date lands on a closing day", () => {
    render(<TripHealth days={[day([stop()])]} request={{ start_date: "2026-11-10" }} />);
    expect(screen.getByText("第 1 天可能闭馆")).toBeInTheDocument();
    expect(screen.getByText(/杭州博物馆 在周二闭馆/)).toBeInTheDocument();
  });

  it("renders nothing when there is no high-confidence issue", () => {
    const openEveryDay = place({ opentime: "周一至周日 09:00-21:00" });
    const { container } = render(<TripHealth days={[day([{ place: openEveryDay, duration: 60, reason: "" }])]} request={{ start_date: "2026-11-10" }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("uses English copy on shared pages", () => {
    render(<TripHealth days={[day([stop()])]} request={{ start_date: null }} lang="en" />);
    expect(screen.getByText("Itinerary check")).toBeInTheDocument();
    expect(screen.getByText(/fixed closing days/)).toBeInTheDocument();
    expect(screen.getByText(/Tuesday/)).toBeInTheDocument();
  });
});
