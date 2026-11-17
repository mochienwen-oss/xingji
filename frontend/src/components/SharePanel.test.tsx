import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../app/providers/ToastProvider";
import { ApiError } from "../lib/api";
import { SharePanel } from "./SharePanel";

const mocked = vi.hoisted(() => ({ api: vi.fn() }));

vi.mock("../lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: mocked.api };
});

type Call = { method: string; url: string; body?: string };

type Server = {
  code: string | null;
  loadError: ApiError | null;
  rotated: string;
  calls: Call[];
};

let server: Server;

function renderPanel() {
  return render(
    <ToastProvider>
      <SharePanel tripId={1} dirty={false} isOwner={true} />
    </ToastProvider>,
  );
}

function openPanel() {
  fireEvent.click(screen.getByRole("button", { name: "分享行程" }));
  return screen.findByRole("dialog", { name: "分享行程" });
}

beforeEach(() => {
  server = { code: null, loadError: null, rotated: "ZZ9Y8X7W", calls: [] };
  mocked.api.mockReset();
  mocked.api.mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    server.calls.push({ method, url, body: typeof init.body === "string" ? init.body : undefined });

    if (method === "GET" && url === "/trips/1/collaborators") return { members: [] };
    if (method === "GET" && url === "/trips/1/share-status") {
      return { visibility: "private", link_active: false };
    }
    if (url === "/trips/1/join-code") {
      if (method === "GET") {
        if (server.loadError) throw server.loadError;
        return { code: server.code };
      }
      if (method === "POST") return { code: server.rotated };
      if (method === "DELETE") {
        server.code = null;
        return undefined;
      }
    }
    throw new Error("未模拟的请求：" + method + " " + url);
  });
});

describe("SharePanel 分享码", () => {
  it("无码时生成分享码，展示 8 位码", async () => {
    renderPanel();
    const dialog = await openPanel();

    fireEvent.click(await within(dialog).findByRole("button", { name: "生成分享码" }));

    expect(await within(dialog).findByText("ZZ9Y8X7W")).toBeInTheDocument();
    expect(
      server.calls.some(
        call =>
          call.method === "POST" &&
          call.url === "/trips/1/join-code" &&
          call.body === JSON.stringify({ rotate: false }),
      ),
    ).toBe(true);
  });

  it("有码时展示，复制走剪贴板并提示成功", async () => {
    server.code = "AB3D5F7H";
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPanel();
    const dialog = await openPanel();

    expect(await within(dialog).findByText("AB3D5F7H")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "复制" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("AB3D5F7H"));
    expect(await screen.findByText("分享码已复制")).toBeInTheDocument();
  });

  it("剪贴板不可用时提示手动复制", async () => {
    server.code = "AB3D5F7H";
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPanel();
    const dialog = await openPanel();

    await within(dialog).findByText("AB3D5F7H");
    fireEvent.click(within(dialog).getByRole("button", { name: "复制" }));

    expect(await screen.findByText("请手动复制分享码")).toBeInTheDocument();
  });

  it("重置先确认再 rotate，成功后更新码并提示", async () => {
    server.code = "AB3D5F7H";
    server.rotated = "ZZ9Y8X7W";
    renderPanel();
    const dialog = await openPanel();
    await within(dialog).findByText("AB3D5F7H");

    fireEvent.click(within(dialog).getByRole("button", { name: "重置" }));
    const confirmBox = await screen.findByRole("dialog", { name: "重置分享码？" });
    expect(
      within(confirmBox).getByText("重置后旧分享码立即失效，已加入的成员不受影响。"),
    ).toBeInTheDocument();
    fireEvent.click(within(confirmBox).getByRole("button", { name: "重置" }));

    await waitFor(() => {
      expect(
        server.calls.some(
          call =>
            call.method === "POST" &&
            call.url === "/trips/1/join-code" &&
            call.body === JSON.stringify({ rotate: true }),
        ),
      ).toBe(true);
    });
    expect(await within(dialog).findByText("ZZ9Y8X7W")).toBeInTheDocument();
    expect(await screen.findByText("分享码已重置")).toBeInTheDocument();
  });

  it("停用先确认，成功后回到无码态并提示", async () => {
    server.code = "AB3D5F7H";
    renderPanel();
    const dialog = await openPanel();
    await within(dialog).findByText("AB3D5F7H");

    fireEvent.click(within(dialog).getByRole("button", { name: "停用" }));
    const confirmBox = await screen.findByRole("dialog", { name: "停用分享码？" });
    fireEvent.click(within(confirmBox).getByRole("button", { name: "停用" }));

    await waitFor(() => {
      expect(
        server.calls.some(call => call.method === "DELETE" && call.url === "/trips/1/join-code"),
      ).toBe(true);
    });
    expect(await screen.findByText("分享码已停用")).toBeInTheDocument();
    expect(await within(dialog).findByRole("button", { name: "生成分享码" })).toBeInTheDocument();
    expect(within(dialog).queryByText("AB3D5F7H")).not.toBeInTheDocument();
  });

  it("非 owner（403/404）时分享码区块整块隐藏", async () => {
    server.loadError = new ApiError("无权限", 403);
    renderPanel();
    const dialog = await openPanel();

    await within(dialog).findByText("还没有协作者。生成邀请链接后发给朋友。");
    await waitFor(() => {
      expect(
        server.calls.some(call => call.method === "GET" && call.url === "/trips/1/join-code"),
      ).toBe(true);
    });
    expect(within(dialog).queryByRole("heading", { name: "分享码" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "生成分享码" })).not.toBeInTheDocument();
  });
});
