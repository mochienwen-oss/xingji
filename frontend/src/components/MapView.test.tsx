import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import type { Day, Route, Stop } from "../types/trip";

vi.mock("../lib/api", () => ({
  api: vi.fn(async () => ({ amap_js_key: "test-key", amap_js_security_code: "test-code" })),
  message: (error: unknown) => String(error),
}));

import { buildRouteLines, MapView } from "./MapView";

type PolylineOptions = {
  path: number[][];
  strokeColor?: string;
  strokeWeight?: number;
  strokeOpacity?: number;
  strokeStyle?: string;
  strokeDasharray?: number[];
  zIndex?: number;
};

// 只实现 MapView 真正调用到的高德 API，避免 jsdom 里加载真实地图脚本。
class MockPolyline {
  options: PolylineOptions;
  constructor(options: PolylineOptions) {
    this.options = options;
    polylines.push(this);
  }
  setMap() {}
  setPath(path: number[][]) {
    this.options.path = path;
  }
}

class MockMap {
  destroy() {}
  remove() {}
  setFitView() {}
  setCity() {}
  setZoomAndCenter() {}
}

class MockMarker {
  setMap() {}
  setLabel() {}
  setTitle() {}
  setPosition() {}
  setzIndex() {}
}

class MockIcon {}

class MockSize {}

let polylines: MockPolyline[] = [];

beforeEach(() => {
  polylines = [];
  (window as any).AMap = {
    Map: MockMap,
    Icon: MockIcon,
    Size: MockSize,
    Marker: MockMarker,
    Polyline: MockPolyline,
  };
});

afterEach(() => {
  delete (window as any).AMap;
});

function stop(id: string, location: string): Stop {
  return {
    place: { id, name: `站${id}`, address: "", location, opentime: "", cost: "", source_time: "" },
    duration: 60,
    reason: "",
  };
}

function route(origin: string, destination: string, polyline: number[][][]): Route {
  return {
    origin,
    destination,
    mode: "transit",
    duration: polyline.length ? 600 : null,
    polyline,
    source_time: "",
  };
}

function day(stops: Stop[], routes: Route[]): Day {
  return { stops, routes };
}

function renderMap(days: Day[]) {
  return render(<MapView days={days} city="杭州" backlog={[]} showBacklog={false} />);
}

describe("buildRouteLines", () => {
  it("缺折线的相邻站点段补虚线直线，有真实折线的段不叠虚线", () => {
    const days = [
      day(
        [stop("a", "120.1,30.2"), stop("b", "120.11,30.21"), stop("c", "120.12,30.22")],
        [
          route("a", "b", [[[120.1, 30.2], [120.11, 30.21]]]),
          route("b", "c", []),
        ],
      ),
    ];
    const lines = buildRouteLines(days);
    expect(lines.get("day-0-gap-1")).toEqual({
      path: [[120.11, 30.21], [120.12, 30.22]],
      dashed: true,
    });
    const keys = [...lines.keys()];
    expect(keys.some((key) => key.includes("gap-0"))).toBe(false);
    expect(lines.get("day-0-0-0-a-b-transit")?.dashed).toBe(false);
  });

  it("没有 route 对象的段也补虚线", () => {
    const days = [
      day([stop("a", "120.1,30.2"), stop("b", "120.11,30.21"), stop("c", "120.12,30.22")], []),
    ];
    const lines = buildRouteLines(days);
    expect(lines.get("day-0-gap-0")?.dashed).toBe(true);
    expect(lines.get("day-0-gap-1")?.path).toEqual([[120.11, 30.21], [120.12, 30.22]]);
  });

  it("折线里只有不足两点的无效路径时仍按缺段处理", () => {
    const days = [
      day([stop("a", "120.1,30.2"), stop("b", "120.11,30.21")], [
        route("a", "b", [[[120.1, 30.2]], []]),
      ]),
    ];
    const lines = buildRouteLines(days);
    expect([...lines.values()]).toEqual([
      { path: [[120.1, 30.2], [120.11, 30.21]], dashed: true },
    ]);
  });

  it("多天的虚线 key 按天隔离", () => {
    const days = [
      day([stop("a", "120.1,30.2"), stop("b", "120.11,30.21")], []),
      day([stop("c", "121.1,30.2"), stop("d", "121.11,30.21")], []),
    ];
    const lines = buildRouteLines(days);
    expect([...lines.keys()]).toEqual(["day-0-gap-0", "day-1-gap-0"]);
  });

  it("坐标缺失的段不画虚线，避免落到 (0,0)", () => {
    const days = [day([stop("a", "bad-location"), stop("b", "120.11,30.21")], [])];
    expect(buildRouteLines(days).size).toBe(0);
  });
});

describe("MapView 路线兜底", () => {
  it("空折线的段画虚线，真实折线只画实线", async () => {
    const days = [
      day(
        [stop("a", "120.1,30.2"), stop("b", "120.11,30.21"), stop("c", "120.12,30.22")],
        [
          route("a", "b", [[[120.1, 30.2], [120.11, 30.21]]]),
          route("b", "c", []),
        ],
      ),
    ];
    renderMap(days);
    await waitFor(() => expect(polylines).toHaveLength(2));
    const dashed = polylines.filter((line) => line.options.strokeStyle === "dashed");
    const solid = polylines.filter((line) => line.options.strokeStyle !== "dashed");
    expect(solid).toHaveLength(1);
    expect(dashed).toHaveLength(1);
    expect(dashed[0].options).toMatchObject({
      path: [[120.11, 30.21], [120.12, 30.22]],
      strokeWeight: 2,
      strokeOpacity: 0.5,
      strokeDasharray: [8, 6],
      zIndex: 40,
    });
    expect(solid[0].options.path).toEqual([[120.1, 30.2], [120.11, 30.21]]);
  });

  it("站点调整后虚线端点原地更新，不重复创建覆盖物", async () => {
    const view = renderMap([day([stop("a", "120.1,30.2"), stop("b", "120.11,30.21")], [])]);
    await waitFor(() => expect(polylines).toHaveLength(1));
    view.rerender(
      <MapView
        days={[day([stop("a", "120.1,30.2"), stop("b", "120.2,30.3")], [])]}
        city="杭州"
        backlog={[]}
        showBacklog={false}
      />,
    );
    await waitFor(() => expect(polylines[0].options.path).toEqual([[120.1, 30.2], [120.2, 30.3]]));
    expect(polylines).toHaveLength(1);
  });
});
