import { beforeEach, describe, expect, it } from "vitest";
import { consumeForkDatePrompt, markForkDatePrompt } from "./forkPrompt";

describe("fork date prompt", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("only returns the prompt for the trip that was just forked", () => {
    markForkDatePrompt(7);
    expect(consumeForkDatePrompt(8)).toBe(false);
    expect(consumeForkDatePrompt(7)).toBe(true);
  });

  it("consumes the prompt so a reload does not reopen the dialog", () => {
    markForkDatePrompt(7);
    expect(consumeForkDatePrompt(7)).toBe(true);
    expect(consumeForkDatePrompt(7)).toBe(false);
    expect(window.sessionStorage.getItem("xingji:date-prompt")).toBeNull();
  });
});
