import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { SessionProvider } from "../app/providers/SessionProvider";
import { SharedTripPage } from "./SharedTripPage";

const mocked = vi.hoisted(() => ({ api: vi.fn(), me: vi.fn() }));

vi.mock("../lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  // SessionProvider 通过命名导出 me() 拉会话，它内部不会经过被 mock 的 api，所以一并替换。
  return { ...actual, api: mocked.api, me: mocked.me };
});

// 地图依赖高德脚本与网络，分享页测试只关心传参与容器。
vi.mock("../components/MapView", () => ({
  MapView: ({ lang }: { lang?: "zh" | "en" }) => <div data-testid="map-view" data-lang={lang ?? "zh"} />,
}));

const writeText = vi.fn(async (_text: string) => {});

function place(id: string, name: string, address: string) {
  return {
    id,
    name,
    address,
    location: "116.39,39.91",
    opentime: "",
    cost: "",
    source_time: "",
    photos: [],
    unavailable: false,
  };
}

function stop(id: string, name: string, address: string, duration: number) {
  return {
    place: place(id, name, address),
    duration,
    reason: "",
    activity: "",
    fixed_time: null,
    fixed_next_day: false,
  };
}

/** 老行程的 transport 存的是中文，分享页要能翻成 chrome 文案。 */
const TRIP = {
  id: 42,
  title: "京都慢行",
  city: "京都",
  owner: "akira",
  request: { city: "京都", days: 2, start_date: "2026-11-05", transport: "公共交通" },
  days: [
    {
      start_time: "09:00",
      end_time: "18:00",
      stops: [
        stop("p1", "清水寺", "京都府京都市東山区", 90),
        stop("p2", "八坂神社", "京都府京都市東山区祇園町", 60),
      ],
      routes: [
        { origin: "p1", destination: "p2", mode: "transit", duration: 600, distance: 800, polyline: [], source_time: "" },
      ],
    },
    {
      start_time: "09:30",
      end_time: "17:00",
      stops: [stop("p3", "岚山竹林", "京都府京都市右京区", 120)],
      routes: [],
    },
  ],
};

type Handler = () => Promise<unknown>;

function mockApi(handlers: { view?: Handler; me?: Handler; fork?: Handler } = {}) {
  mocked.me.mockImplementation(() => mocked.api("/me"));
  mocked.api.mockImplementation((url: string) => {
    if (url === "/shares/view") return handlers.view ? handlers.view() : Promise.resolve(TRIP);
    if (url === "/me") return handlers.me ? handlers.me() : Promise.reject(new ApiError("未登录", 401));
    if (url === "/shares/fork") return handlers.fork ? handlers.fork() : Promise.resolve({ id: 7 });
    return Promise.resolve(null);
  });
}

function renderPage(props: { token: string; onLogin?: () => void } = { token: "tok" }) {
  // 分享页从全局 SessionProvider 读登录态，测试要用同样的上下文（/me 由 mockApi 提供）。
  return render(
    <SessionProvider>
      <SharedTripPage {...props} />
    </SessionProvider>,
  );
}

/** user-event 的 setup 会用自己的剪贴板 stub 覆盖 navigator.clipboard，装好后再换回我们的 spy。 */
function setupUser() {
  const user = userEvent.setup();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return user;
}

beforeEach(() => {
  mocked.api.mockReset();
  writeText.mockClear();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  document.documentElement.lang = "zh-CN";
});

describe("SharedTripPage", () => {
  it("renders the trip title, meta, days and numbered stops", async () => {
    mockApi();
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "京都慢行" })).toBeInTheDocument();
    expect(screen.getByText("2 天")).toBeInTheDocument();
    expect(screen.getByText("公交")).toBeInTheDocument();
    expect(screen.getByText("只读分享")).toBeInTheDocument();
    expect(screen.getByText("由 @akira 分享")).toBeInTheDocument();
    expect(screen.getByText("总里程")).toBeInTheDocument();
    expect(screen.getByText("800 米")).toBeInTheDocument();

    expect(screen.getByRole("tab", { name: "总览" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "第 1 天" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "第 2 天" })).toBeInTheDocument();

    expect(screen.getByRole("heading", { level: 3, name: "清水寺" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "八坂神社" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "岚山竹林" })).toBeInTheDocument();
    expect(screen.getByText("1.1")).toBeInTheDocument();
    expect(screen.getByText("1.2")).toBeInTheDocument();
    expect(screen.getByText("2.1")).toBeInTheDocument();

    expect(screen.getByText("地图与路线由高德提供")).toBeInTheDocument();
    expect(screen.getByTestId("map-view")).toHaveAttribute("data-lang", "zh");
    expect(screen.getByRole("link", { name: "打开行迹，规划我的路线" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制此行程" })).toBeInTheDocument();
    // AppShell 已经提供了 main，分享页不能再套一层。
    expect(document.querySelectorAll("main")).toHaveLength(0);
  });

  it("switches every chrome label to English but keeps the proper nouns", async () => {
    mockApi();
    const user = setupUser();
    renderPage();
    await screen.findByRole("heading", { level: 1, name: "京都慢行" });

    await user.click(screen.getByRole("button", { name: "English" }));

    expect(document.documentElement.lang).toBe("en");
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Day 1" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Day 2" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Map & route" })).toBeInTheDocument();
    expect(screen.getByText("Map data and routes by Amap")).toBeInTheDocument();
    expect(screen.getByText("2 days")).toBeInTheDocument();
    expect(screen.getByText("Distance")).toBeInTheDocument();
    expect(screen.getByText("800 m")).toBeInTheDocument();
    expect(screen.getByText("Transit")).toBeInTheDocument();
    expect(screen.getByText("Suggested stay: 90 min")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Show on map" })).toHaveLength(3);
    expect(screen.getByText(/Hours, tickets and transit may change/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan my own route" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy this trip" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Explore" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chinese" })).toBeInTheDocument();
    expect(screen.getByTestId("map-view")).toHaveAttribute("data-lang", "en");

    // 城市、景点等专名保持中文。
    expect(screen.getByRole("heading", { level: 1, name: "京都慢行" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "清水寺" })).toBeInTheDocument();

    expect(screen.queryByText("总览")).toBeNull();
    expect(screen.queryByText("复制此行程")).toBeNull();
    expect(screen.queryByText("只读分享")).toBeNull();
  });

  it("shows the ended state for a revoked share instead of an error", async () => {
    mockApi({ view: () => Promise.reject(new ApiError("分享不存在或已撤销。", 404)) });
    const user = setupUser();
    renderPage();

    expect(await screen.findByText("这条分享已结束")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去行迹看看" })).toHaveAttribute("href", "#/explore");
    // 原始错误不能漏到页面上。
    expect(screen.queryByText(/分享不存在或已撤销/)).toBeNull();
    expect(screen.queryByText(/404/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByText("This share has ended")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Explore Trip" })).toBeInTheDocument();
  });

  it("treats a 410 link as ended too", async () => {
    mockApi({ view: () => Promise.reject(new ApiError("Gone", 410)) });
    renderPage();
    expect(await screen.findByText("这条分享已结束")).toBeInTheDocument();
    expect(screen.queryByText("重试")).toBeNull();
  });

  it("offers a retry when loading fails, then renders the itinerary", async () => {
    let attempts = 0;
    mockApi({
      view: () => {
        attempts += 1;
        return attempts === 1 ? Promise.reject(new Error("网络不可用")) : Promise.resolve(TRIP);
      },
    });
    const user = setupUser();
    renderPage();

    expect(await screen.findByText("暂时打不开这份分享")).toBeInTheDocument();
    expect(screen.queryByText(/网络不可用/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByRole("heading", { level: 1, name: "京都慢行" })).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("keeps the read-only CTA copyable by cloning the share link to the clipboard", async () => {
    mockApi({ fork: () => Promise.reject(new ApiError("复制失败", 500)) });
    const user = setupUser();
    renderPage();
    await screen.findByRole("heading", { level: 1, name: "京都慢行" });

    await user.click(screen.getByRole("button", { name: "复制此行程" }));
    expect(await screen.findByText("复制没有成功，请复制下面的分享链接。")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "分享链接" })).toHaveValue(window.location.href);

    await user.click(screen.getByRole("button", { name: "复制分享链接" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(window.location.href));
    expect(await screen.findByText("分享链接已复制。")).toBeInTheDocument();
  });

  it("asks a guest to sign in when forking needs an account", async () => {
    mockApi({ fork: () => Promise.reject(new ApiError("未登录", 401)) });
    const onLogin = vi.fn();
    const user = setupUser();
    renderPage({ token: "tok", onLogin });
    await screen.findByRole("heading", { level: 1, name: "京都慢行" });

    await user.click(screen.getByRole("button", { name: "复制此行程" }));
    expect(await screen.findByText(/登录后即可把这份行程复制到我的行程/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /登录/ }));
    expect(onLogin).toHaveBeenCalledTimes(1);
  });

  it("forks the trip for a signed-in reader and opens it with a date prompt", async () => {
    mockApi({ me: () => Promise.resolve({ username: "alice" }) });
    const user = setupUser();
    renderPage();
    await screen.findByRole("heading", { level: 1, name: "京都慢行" });

    await user.click(await screen.findByRole("button", { name: "复制此行程到我的行程" }));

    await waitFor(() => expect(window.location.hash).toBe("#/trips/7"));
    expect(window.sessionStorage.getItem("xingji:date-prompt")).toBe("7");
    expect(mocked.api).toHaveBeenCalledWith("/shares/fork", expect.objectContaining({ method: "POST" }));
  });
});
