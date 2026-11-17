import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../app/providers/ToastProvider";
import type { Stop } from "../../types/trip";
import { StopDetailSheet } from "./StopDetailSheet";

/**
 * 需求出处 README.md:87：「固定事项需手动选择是否在次日。」
 * 详情面板要把 fixed_time 与 fixed_next_day 一起暴露给用户：勾选固定时间后
 * 才可选择“次日（凌晨）”，保存时两者一起回传；取消固定时间则回传 (null, false)。
 */

function makeStop(overrides: Partial<Stop> = {}): Stop {
  return {
    place: {
      id: "p1",
      name: "西湖",
      address: "杭州市西湖区",
      location: "120.15,30.25",
      opentime: "",
      cost: "",
      source_time: "",
    },
    duration: 90,
    reason: "",
    ...overrides,
  };
}

function renderSheet(stop: Stop, onFixedTime = vi.fn()) {
  render(
    <ToastProvider>
      <StopDetailSheet
        open
        stop={stop}
        index={0}
        total={2}
        busy={false}
        transport="transit"
        onClose={() => {}}
        onDuration={() => {}}
        onFixedTime={onFixedTime}
        onMove={() => {}}
        onDelete={() => {}}
      />
    </ToastProvider>,
  );
  return onFixedTime;
}

describe("StopDetailSheet 固定时间（README:87 手动选择是否在次日）", () => {
  it("勾选固定时间、填入 00:30 并勾选次日，保存时回传 ('00:30', true)", () => {
    const onFixedTime = renderSheet(makeStop());
    const nextDay = screen.getByRole("checkbox", { name: "次日（凌晨）" });
    // 没有固定时间时「次日」不可用，避免保存出没有时间的次日安排。
    expect(nextDay).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: "固定到具体时间" }));
    fireEvent.change(screen.getByLabelText("固定时间"), { target: { value: "00:30" } });
    expect(nextDay).toBeEnabled();
    fireEvent.click(nextDay);
    fireEvent.click(screen.getByRole("button", { name: "保存固定时间" }));

    expect(onFixedTime).toHaveBeenCalledTimes(1);
    expect(onFixedTime).toHaveBeenCalledWith("00:30", true);
  });

  it("取消固定时间后保存，回传 (null, false)，不能残留次日标记", () => {
    const onFixedTime = renderSheet(makeStop({ fixed_time: "10:00", fixed_next_day: true }));
    const fixedOn = screen.getByRole("checkbox", { name: "固定到具体时间" });
    expect(fixedOn).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "次日（凌晨）" })).toBeChecked();

    fireEvent.click(fixedOn);
    fireEvent.click(screen.getByRole("button", { name: "保存固定时间" }));

    expect(onFixedTime).toHaveBeenCalledTimes(1);
    expect(onFixedTime).toHaveBeenCalledWith(null, false);
  });

  it("原来固定在同一天时默认不勾次日，保存保持 false", () => {
    const onFixedTime = renderSheet(makeStop({ fixed_time: "10:00" }));
    expect(screen.getByRole("checkbox", { name: "次日（凌晨）" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "保存固定时间" }));
    expect(onFixedTime).toHaveBeenCalledWith("10:00", false);
  });
});
