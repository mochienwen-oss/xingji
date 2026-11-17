import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Trip } from "../../types/trip";
import { AskAiSheet } from "./AskAiSheet";

vi.mock("../../lib/agent", () => ({
  // 模拟后端把对话结果落库后的 saved 事件：onDone 回执携带新版本号。
  streamAssistant: (
    _tripId: number,
    _body: { message: string; history: unknown[]; version: number },
    handlers: { onDone?: (payload: { reply?: string; changed?: boolean; version?: number }) => void },
  ) => {
    handlers.onDone?.({ reply: "已经记下来了。", changed: false, version: 6 });
    return () => {};
  },
  streamPlanningChat: () => () => {},
}));

const trip: Trip = {
  id: 7,
  version: 5,
  title: "京都一日",
  request: {
    city: "京都",
    days: 1,
    start_date: null,
    travelers: 2,
    interests: "",
    pace: "适中",
    budget: "",
    must_visit: "",
    transport: "walking",
  },
  days: [],
  backlog: [],
};

describe("AskAiSheet undo", () => {
  it("shows the last AI adjustment with a one-step undo", () => {
    const onUndo = vi.fn();
    render(
      <AskAiSheet
        open
        trip={null}
        dirty={false}
        messages={[]}
        setMessages={() => {}}
        onClose={() => {}}
        onSuggestion={() => {}}
        onRefreshTrip={async () => true}
        onNotify={() => {}}
        undoAvailable
        onUndo={onUndo}
      />,
    );
    expect(screen.getByText("已应用 AI 调整")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });
});

describe("AskAiSheet version ack", () => {
  beforeAll(() => {
    // jsdom 未实现 scrollIntoView，而 TravelChat 挂载时就会调用。
    window.HTMLElement.prototype.scrollIntoView = () => {};
  });

  it("forwards the version from the agent result to ackVersion", () => {
    const ackVersion = vi.fn();
    render(
      <AskAiSheet
        open
        trip={trip}
        dirty={false}
        messages={[]}
        setMessages={() => {}}
        onClose={() => {}}
        onSuggestion={() => {}}
        onRefreshTrip={async () => true}
        onNotify={() => {}}
        ackVersion={ackVersion}
      />,
    );
    const input = screen.getByLabelText("描述旅行想法");
    fireEvent.change(input, { target: { value: "帮我加一个景点" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(ackVersion).toHaveBeenCalledWith(6);
  });
});
