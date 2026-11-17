import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** 用假的 /config 响应装配一个干净的 mapLoader 模块（模块内有 Promise 单例）。 */
async function setupLoader(config: unknown) {
  vi.resetModules();
  vi.doMock("./config", () => ({
    loadAppConfig: vi.fn().mockResolvedValue(config),
  }));
  return await import("./mapLoader");
}

describe("loadAmap：地图脚本装载", () => {
  beforeEach(() => {
    delete (window as unknown as { AMap?: unknown }).AMap;
    document.head.innerHTML = "";
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.doUnmock("./config");
  });

  it("页面已有 AMap 时直接复用，不再读配置", async () => {
    const existing = { Marker: function Marker() {} };
    (window as unknown as { AMap?: unknown }).AMap = existing;
    const { loadAmap } = await setupLoader(undefined);

    await expect(loadAmap()).resolves.toBe(existing);
    const config = await import("./config");
    expect(vi.mocked(config.loadAppConfig)).not.toHaveBeenCalled();
  });

  it("配置里没有高德密钥时给出可读的报错", async () => {
    const { loadAmap } = await setupLoader({ amap_js_key: "" });
    await expect(loadAmap()).rejects.toThrow("配置高德地图密钥后显示地图");
  });

  it("有密钥和有安全密钥时注入脚本，AMap 就绪后返回命名空间", async () => {
    vi.useFakeTimers();
    const { loadAmap } = await setupLoader({
      amap_js_key: "js-key/1",
      amap_js_security_code: "sec-1",
    });
    const pending = loadAmap();
    await vi.advanceTimersByTimeAsync(0);

    const script = document.getElementById("amap-js-api") as HTMLScriptElement | null;
    expect(script).not.toBeNull();
    expect(script?.src).toContain("key=js-key%2F1");
    expect((window as unknown as { _AMapSecurityConfig?: unknown })._AMapSecurityConfig).toEqual({
      securityJsCode: "sec-1",
    });

    const namespace = { Marker: function Marker() {} };
    (window as unknown as { AMap?: unknown }).AMap = namespace;
    await vi.advanceTimersByTimeAsync(120);
    await expect(pending).resolves.toBe(namespace);
  });
});
